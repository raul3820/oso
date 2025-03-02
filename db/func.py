import os
import asyncpg
import logfire
import time
import re
from asyncpg import Pool
from typing import Type, Awaitable, List, Optional, Callable, TypeVar, ParamSpec
from enum import Enum
from db.struct import MsgClassification, AppMsg
from functools import wraps

# Define types for better type hinting
P = ParamSpec('P')
R = TypeVar('R')

def validate_query(query_string):
    query_string = query_string.lower().strip()
    """Validates the query string for pipe lock decorator."""
    if not re.search(r"^with\b", query_string):
        raise ValueError("Query must begin with 'with'")
    if not re.search(r".*\bmsgs\s+as\b", query_string):
        raise ValueError("Query must contain 'msgs as'")
    if not re.search(r"\)$", query_string):
        raise ValueError("Query must end with ')'")
    return query_string

def with_pipe_lock(msg_class: Type[AppMsg] = AppMsg) -> Callable[[Callable[P, Awaitable[None]]], Callable[P, Awaitable[List[AppMsg]]]]:
    """Decorator for atomically fetching and locking messages.
    
    Decorated functions must define `query` as an inline SQL string
    to select candidate messages. This decorator performs an atomic fetch and lock
    and returns a list of locked AppMsg objects.
    """

    def decorator(get_candidates_func: Callable[P, Awaitable[None]]) -> Callable[P, Awaitable[List[AppMsg]]]:
        @wraps(get_candidates_func)
        async def wrapper(self, *args: P.args, **kwargs: P.kwargs) -> List[AppMsg]:
            # Execute the original function to define 'query'
            query_string = await get_candidates_func(self, *args, **kwargs)
            query_string = validate_query(query_string)
            
            now_timestamp = int(time.time())
            timeout_threshold = now_timestamp - self.lock_timeout_seconds
            locking_query = f"""
                {query_string}
                , updated as (
                    update oso.msg as target_table
                    set locked_at = {now_timestamp}
                    from msgs
                    where target_table.msg_id = msgs.msg_id
                    and (target_table.locked_at is null or target_table.locked_at < {timeout_threshold})
                    returning target_table.msg_id
                )
                select msgs.*
                from msgs
                inner join updated using(msg_id);
            """
            try:
                async with self.pool.acquire() as connection:
                    locked_rows = await connection.fetch(locking_query)
                    locked_messages: List[AppMsg] = [msg_class(**dict(row)) for row in locked_rows]
                    return locked_messages

            except Exception as e:
                logfire.exception(f"DB -- Error during atomic lock acquisition: {e}")
                return []

        return wrapper

    return decorator


class DBFunctions:
    def __init__(self, lock_timeout_seconds: int = 1):
        self.pool: Optional[Pool] = None
        self.lock_timeout_seconds = lock_timeout_seconds

    async def connect(self):
        """Initialize the database connection pool."""
        postgres_url = os.getenv("POSTGRES_URL")

        if not postgres_url:
            raise ValueError("POSTGRES_URL environment variable not set")

        try:
            pool = await asyncpg.create_pool(dsn=postgres_url)
            logfire.info("DB -- Database pool created successfully")
            self.pool = pool
        except Exception as e:
            logfire.exception(f"DB -- Error creating DB pool: {e}")
            raise

    async def create_schema(self):
        """Create database schema using the SQL script."""
        if not self.pool:
            raise ValueError("Database pool not initialized")

        script_path = os.path.abspath(__file__)
        db_dir = os.path.dirname(script_path)
        sql_file = os.path.join(db_dir, 'create.sql')

        with open(sql_file, 'r') as f:
            sql = f.read()
        
        embeddings_ndim = os.getenv("EMBEDDINGS_NDIM")
        if embeddings_ndim is None:
            logfire.exception("DB -- Error: EMBEDDINGS_NDIM environment variable is not set.")
            return
        sql = sql.replace("${embeddings_ndim}", embeddings_ndim)
        
        postgres_url = os.getenv("POSTGRES_URL")
        if postgres_url is None:
            logfire.exception("DB -- Error: POSTGRES_URL environment variable is not set.")
            return
        
        try:
            async with self.pool.acquire() as connection:
                await connection.execute(sql)
            logfire.info("DB -- Schema created successfully")
        except Exception as e:
            logfire.exception(f"DB -- Error executing SQL: {e}")
            raise

    def _build_upsert_query(self, msg: AppMsg):
        """
        Build an INSERT ... ON CONFLICT query dynamically based on which fields are not None.
        Assumes that:
        - msg.msg_id is the primary key and must always be provided.
        - All other fields, if not None, will be both inserted and used for updating.
        """
        columns = []
        values = []
        placeholders = []
        update_clauses = []
        param_index = 1

        # Process all fields except msg_id.
        for field, value in msg.model_dump(exclude_none=True).items():
            if field == 'msg_id':
                continue
            if isinstance(value, Enum):
                value = value.value
            columns.append(field)
            values.append(value)
            placeholders.append(f"${param_index}")
            update_clauses.append(f"{field} = EXCLUDED.{field}")
            param_index += 1

        # Append msg_id at the end.
        columns.append('msg_id')
        values.append(msg.msg_id)
        placeholders.append(f"${param_index}")

        # Build the INSERT query.
        query = f"INSERT INTO oso.msg ({', '.join(columns)}) VALUES ({', '.join(placeholders)}) "

        if update_clauses:
            query += "ON CONFLICT (msg_id) DO UPDATE SET " + ", ".join(update_clauses)
        else:
            query += "ON CONFLICT (msg_id) DO NOTHING"

        return query, values
    
    async def upsert_msgs(self, msgs: List[AppMsg]) -> bool:
        """
        Insert or update messages dynamically.
        For each msg, only non-None fields (besides msg_id) will be inserted/updated.
        """
        try:
            # Use one connection and a transaction
            async with self.pool.acquire() as connection:
                async with connection.transaction():
                    for msg in msgs:
                        query, params = self._build_upsert_query(msg)
                        # Execute each query individually.
                        await connection.execute(query, *params)
            logfire.info(f"DB -- Upserted {len(msgs)} messages.")
            return True
        except asyncpg.PostgresError as e:
            logfire.exception(f"DB -- Error upserting messages: {e}")
            return False
        except Exception as e:
            logfire.exception(f"DB -- An unexpected error occurred: {e}")
            return False

    def _build_update_query(self, msg: AppMsg):
        """
        Build an UPDATE query dynamically based on which fields are not None.
        Assumes that:
        - msg.msg_id is the primary key and must always be provided.
        - All other fields, if not None, will be updated.
        """
        set_clauses = []
        values = []
        # Placeholder numbering starts at 1.
        param_index = 1

        # Iterate over all attributes of msg.
        # (Adjust if your AppMsg does not use __dict__ or you want a specific order.)
        for field, value in msg.model_dump(exclude_none=True).items():
            if field == 'msg_id':
                continue
            # Convert Enum values to their underlying value.
            if isinstance(value, Enum):
                value = value.value
            set_clauses.append(f"{field} = ${param_index}")
            values.append(value)
            param_index += 1

        # If no fields besides msg_id are provided, there's nothing to update.
        if not set_clauses:
            return None, None

        # Build the base UPDATE query using msg_id in the WHERE clause.
        query = f"UPDATE oso.msg SET {', '.join(set_clauses)} WHERE msg_id = ${param_index}"
        values.append(msg.msg_id)
        return query, values

    async def update_msgs(self, msgs: List[AppMsg]) -> bool:
        """
        Update messages dynamically.
        For each msg, only non-None fields (besides msg_id) will be updated.
        """
        try:
            # Use one connection and a transaction.
            async with self.pool.acquire() as connection:
                async with connection.transaction():
                    for msg in msgs:
                        query, params = self._build_update_query(msg)
                        if query:
                            # Execute the update query only if there are fields to update.
                            await connection.execute(query, *params)
                        else:
                            logfire.warning(f"No fields to update for message with msg_id {msg.msg_id}.")
            logfire.info(f"DB -- Updated {len(msgs)} messages.")
            return True
        except asyncpg.PostgresError as e:
            logfire.exception(f"DB -- Error updating messages: {e}")
            return False
        except Exception as e:
            logfire.exception(f"DB -- An unexpected error occurred: {e}")
            return False

    @with_pipe_lock()
    async def get_locked_msgs_to_classify(self, ex: List[MsgClassification], limit=100, lookback='1 week') -> List[AppMsg]:
        """Fetches msgs from the database pending clssification."""
        ex_values = [e.value for e in ex]
        return f"""
            with 
            ex as (
                select
                sender
                from oso.msg
                where 
                extract(epoch from current_timestamp - interval '{lookback}') < created_at
                and is_receiver_me
                and classification = any(array{ex_values}::text[])
                group by 1
            ),
            msgs as ( 
                select msg_id, body 
                from oso.msg
                where
                extract(epoch from current_timestamp - interval '{lookback}') < created_at
                and is_receiver_me
                and classification is null
                and sender not in (select sender from ex)
                order by created_at limit {limit}
            )
            """

    @with_pipe_lock()
    async def get_locked_msgs_to_reply(self, any: List[MsgClassification], ex: List[MsgClassification], limit=100, lookback='1 week') -> List[AppMsg]:
        """Fetches msgs from the database to reply."""
        any_values = [e.value for e in any]
        ex_values = [e.value for e in ex]
        return f"""
            with 
            ex as (
                select
                sender
                from oso.msg
                where extract(epoch from current_timestamp - interval '{lookback}') < created_at
                and is_receiver_me
                and classification = any(array{ex_values}::text[])
                group by 1
            ),
            msgs as (
                select msg_id, sender, receiver, source
                from(
                    select distinct on (sender) 
                    msg_id, 
                    sender,
                    receiver,
                    source,
                    reply_body is null as not_has_reply
                    from oso.msg 
                    where
                    extract(epoch from current_timestamp - interval '{lookback}') < created_at
                    and is_receiver_me
                    and sender not in (select sender from ex)
                    and classification = any(array{any_values}::text[])
                    order by sender, created_at desc
                ) t
                where not_has_reply
                limit {limit}
            )
            """
    
    @with_pipe_lock()
    async def get_locked_msgs_to_summarize(self, any: List[MsgClassification], ex: List[MsgClassification], limit=100, lookback='1 week') -> List[AppMsg]:
        """Fetches msgs from the database."""

        any_values = [e.value for e in any]
        ex_values = [e.value for e in ex]

        return f"""
            with 
            ex as (
                select
                sender
                from oso.msg
                where extract(epoch from current_timestamp - interval '{lookback}') < created_at
                and is_receiver_me
                and classification = any(array{ex_values}::text[])
                group by 1
            ),
            msgs as ( 
                select msg_id, body 
                from oso.msg 
                where 
                extract(epoch from current_timestamp - interval '{lookback}') < created_at
                and is_receiver_me
                and summary is null
                and classification = any(array{any_values}::text[])
                and sender not in (select sender from ex)
                order by created_at limit {limit} 
            )
            """

    @with_pipe_lock()
    async def get_locked_replies_to_send(self, limit=100) -> List[AppMsg]:
        """Fetches and atomically locks candidate AppMsg objects for replies to send."""
        return f"""
            with msgs as (
                select msg_id, subject, sender, body, reply_body
                from oso.msg
                where
                    reply_body is not null
                    and reply_id is null
                order by created_at
                limit {limit}
            )
            """

    @with_pipe_lock()
    async def get_locked_summaries_to_share(self, limit=100) -> List[AppMsg]:
        """Fetch replies to send from the database."""
        
        return f"""
        with msgs as(
            select msg_id, summary, images 
            from oso.msg
            where
            summary is not null
            and post_id is null
            order by created_at 
            limit {limit}
            )
        """

    async def get_thread_of_msgs(self, msg: AppMsg, lookback='1 week', thread_limit=3) -> List[AppMsg]:
        """Fetches msgs from the database."""

        query = f"""
            select *
            from (
                select msg_id, created_at, body, reply_body, classification
                from oso.msg
                where
                extract(epoch from current_timestamp - interval '{lookback}') < created_at
                and source = '{msg.source.value}'
                and (
                    (sender = '{msg.sender}' and receiver = '{msg.receiver}') or
                    (sender = '{msg.receiver}' and receiver = '{msg.sender}')
                )
                and is_receiver_me
                order by created_at desc
                limit {thread_limit}
                ) as t
            order by created_at
            ;"""

        try:
            async with self.pool.acquire() as connection:
                result = await connection.fetch(query)
                
                return [AppMsg(**row) for row in result]
        
        except Exception as e:
            logfire.exception(f"DB -- Error while fetching msgs from thread: {e}")
            return []

    async def release_locks(self, messages: List[AppMsg]) -> bool:
        """Releases locks on a list of AppMsg objects."""
        if not messages:
            return True

        msg_ids_to_release = [msg.msg_id for msg in messages]
        query = f"""
            update oso.msg
            set locked_at = null
            where msg_id = any(array{msg_ids_to_release}::text[]);
        """
        try:
            async with self.pool.acquire() as connection:
                await connection.execute(query)
            return True
        
        except Exception as e:
            logfire.exception(f"DB -- Error releasing locks: {e}")
            return False
 
    async def close(self):
        """Close the database connection pool."""
        if self.pool:
            await self.pool.close()
            logfire.info("DB -- Database pool closed successfully")

