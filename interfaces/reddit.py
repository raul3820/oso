import os
import pickle
import socket
import random
import asyncio
import httpx
import logfire
from asyncpraw.reddit import Reddit
from asyncpraw.models import Comment, Message, Redditor
from dotenv import load_dotenv
from typing import Optional, List, AsyncGenerator
from db.struct import AppMsg, MsgSource
from db.func import DBFunctions as DB
from models import agent
load_dotenv()
logfire.configure(send_to_logfire='never', scrubbing=False)


script_dir = os.path.dirname(os.path.abspath(__file__))
token_path = os.path.join(os.path.dirname(script_dir), 'temp', 'reddit_token.pickle')
client_id = os.environ["REDDIT_CLIENT_ID"]
client_secret = os.environ["REDDIT_CLIENT_SECRET"]
user_agent = os.environ["REDDIT_USER_AGENT"]
check_every_seconds = int(os.getenv("CHECK_EVERY_SECONDS", 300))


async def get_scopes() -> List[str]:
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://www.reddit.com/api/v1/scopes.json",
                headers={"User-Agent": "fetch-scopes by u/bboe"},
            )
            response.raise_for_status()
            return sorted(list(response.json().keys()))
    except httpx.HTTPError as e:
        logfire.error(f"HTTP error occurred while fetching scopes: {e}")
        return []
    except Exception as e:
        logfire.error(f"An error occurred while fetching scopes: {e}")
        return []

def receive_connection():
    """Wait for and then return a connected socket..

    Opens a TCP connection on port 8080, and waits for a single client.

    """
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("localhost", 8080))
    server.listen(1)
    client = server.accept()[0]
    server.close()
    return client

def send_message(client, message): # Keeping send_message for the socket communication part
    """Send message to client and close the connection."""
    logfire.info(message)
    client.send(f"HTTP/1.1 200 OK\r\n\r\n{message}".encode())
    client.close()

async def get_creds():
    try:
        reddit_auth = Reddit(
            user_agent=user_agent,
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri="http://localhost:8080",
        )
        scopes = await get_scopes()
        state = str(random.randint(0, 65000))
        url = reddit_auth.auth.url(duration="permanent", scopes=scopes, state=state)
        print(f"Now open this url in your browser: {url}")

        client = receive_connection()
        data = client.recv(1024).decode("utf-8")
        param_tokens = data.split(" ", 2)[1].split("?", 1)[1].split("&")
        params = dict([token.split("=") for token in param_tokens])

        if state != params["state"]:
            send_message(
                client,
                f"State mismatch. Expected: {state} Received: {params['state']}",
            )
            return None
        if "error" in params:
            send_message(client, params["error"])
            return None

        creds = await reddit_auth.auth.authorize(params["code"])
        send_message(client, f"Refresh token: {creds}")

        with open(token_path, 'wb') as token:
            pickle.dump(creds, token)

        return creds
    except Exception as e:
        logfire.error(f"Error during Reddit login flow: {e}")
        return None

async def get_reddit_client() -> Optional[Reddit]:
    creds = None
    try:
        if os.path.exists(token_path):
            with open(token_path, 'rb') as token:
                creds = pickle.load(token)

        if not creds:
            creds = await get_creds()

        try: # Wrap the reddit client creation with refresh token
            reddit_client = Reddit(
                client_id=client_id,
                client_secret=client_secret,
                user_agent=user_agent,
                refresh_token=creds,
                redirect_uri="http://localhost:8080",
            )
            me = await reddit_client.user.me()
            logfire.info(f"Reddit logged in as: {me.name}")

            return reddit_client

        except Exception as e:
            logfire.warning(f"Error getting Reddit client: {e}. Re-authenticating...")
            creds = await get_creds()
            if creds:
                reddit_client = Reddit(
                    client_id=client_id,
                    client_secret=client_secret,
                    user_agent=user_agent,
                    refresh_token=creds,
                    redirect_uri="http://localhost:8080",
                )
                me = await reddit_client.user.me()
                logfire.info(f"Reddit logged in as: {me.name}")

                return reddit_client
            else:
                return None

    except Exception as e:
        logfire.exception(f"An error occurred during Reddit authentication: {e}")
        return None

def parse_reddit_message(item: Comment | Message, is_receiver_me: bool) -> Optional[AppMsg]:
    """Wraps the reddit inbox stream generator to yield instances of RedditMessage."""
    try:
        author_name = None
        if hasattr(item, 'author') and item.author:
            author_name = item.author.name

        dest_name = None
        if hasattr(item, 'dest') and item.dest:
            dest_name = item.dest.name
        elif hasattr(item, 'recipient') and item.recipient:
            dest_name = item.recipient.name

        body = None
        if hasattr(item, 'body'):
            body = item.body

        subject = None
        if hasattr(item, 'subject'):
            subject = item.subject

        source = None
        if isinstance(item, Comment):
            source = MsgSource.RedditComment
        elif isinstance(item, Message):
            source = MsgSource.RedditMessage

        return AppMsg(
            msg_id=item.id,
            created_at=item.created_utc,
            source=source,
            sender=author_name,
            receiver=dest_name,
            is_receiver_me=is_receiver_me,
            subject=subject,
            body=body,
        )

    except Exception as e:
        logfire.exception(f"Exception while parsing reddit message {item.id if hasattr(item, 'id') else 'unknown'}: {e}")
        return None

async def _send_reply(client: Reddit, msg: AppMsg) -> Optional[AppMsg]:
    """Sends a reply to the given message."""
    try:
        message = await client.inbox.message(msg.msg_id)
        item = await message.reply(msg.reply_body)
        new_msg = parse_reddit_message(item, False)
        msg.reply_id = new_msg.msg_id
        return new_msg

    except Exception as e:
        logfire.exception(f"Exception while sending reply to {msg.msg_id}: {e}")
        return None

async def send_replies(client: Reddit, db: DB) -> bool:
    """Sends replies to msgs that have been processed in the DB."""
    try:
        locked_msgs = await db.get_locked_replies_to_send()

        if not locked_msgs:
            logfire.info("No replies to send.")
            return True
        
        tasks = [_send_reply(client ,msg) for msg in locked_msgs]
        sent_msgs = await asyncio.gather(*tasks)

        if not sent_msgs:
            logfire.error("No replies were sent successfully.")
            return False
        
        r0 = await db.update_msgs(locked_msgs)
        r1 = await db.upsert_msgs(sent_msgs)
        await db.release_locks(locked_msgs)

        r = r0 and r1
        if r:
            logfire.info(f"Successfully sent {len(sent_msgs)} replies.")
        return r
    
    except Exception as e:
        logfire.exception(f"Error sending replies: {e}")
        return False

async def _post_to_profile(client: Reddit, msg: AppMsg, me: Redditor) -> Optional[AppMsg]:
    """Posts the summary of the given message to the user's profile."""
    try:
        title = msg.summary.split('.')[0][:128] + ' ...'
        submission = await me.subreddit.submit(title=title, selftext=msg.summary)
        msg.post_id = submission.id
        
        return msg

    except Exception as e:
        logfire.exception(f"Exception while posting to profile: {e}")
        return None

async def post_summaries(client: Reddit, db: DB, me: Redditor)-> bool:
    """Posts stories to Reddit."""
    try:
        locked_msgs = await db.get_locked_summaries_to_share()
        
        if not locked_msgs:
            logfire.info("No story summaries to share.")
            return True
        
        tasks = [_post_to_profile(client, msg, me) for msg in locked_msgs]
        posted_msgs = await asyncio.gather(*tasks)

        if not posted_msgs:
            logfire.error("No valid summaries posted.")
            return False
        
        r = await db.update_msgs(posted_msgs)
        await db.release_locks(locked_msgs)        
        return r
        
    except Exception as e:
        logfire.exception(f"Error posting summaries: {e}")
        return False


async def read_loop(client: Reddit, db: DB):
    """Runs the main function in a loop with specified interval."""
    while True:
        try:
            logfire.info("Starting to get reddit messages stream.")
            async for item in client.inbox.stream():
                msg = parse_reddit_message(item, True)
                await db.upsert_msgs([msg])
                await agent.classify_msgs(db)
                await agent.generate_replies(db)
                await agent.generate_summaries(db)
                await asyncio.sleep(check_every_seconds)

        except asyncio.CancelledError:
            logfire.info("Reddit service cancelled, exiting read loop.")
            break
        except Exception as e:
            logfire.exception(f"An error occurred in Reddit read loop: {e}")
            await asyncio.sleep(check_every_seconds)

async def reply_loop(client: Reddit, db: DB):
    """Runs the main function in a loop with specified interval."""
    while True:
        try:
            await send_replies(client, db)
            await asyncio.sleep(check_every_seconds)
            
        except asyncio.CancelledError:
            logfire.info("Reddit service cancelled, exiting reply loop.")
            break
        except Exception as e:
            logfire.exception(f"An error occurred in Reddit read loop: {e}")
            await asyncio.sleep(check_every_seconds)

async def post_loop(client: Reddit, db: DB):
    """Runs the main function in a loop with specified interval."""
    me = await client.user.me()
    while True:
        try:
            await post_summaries(client, db, me)
            await asyncio.sleep(check_every_seconds)
        except asyncio.CancelledError:
            logfire.info("Reddit service cancelled, exiting post loop.")
            break
        except Exception as e:
            logfire.exception(f"An error occurred in Reddit read loop: {e}")
            await asyncio.sleep(check_every_seconds)

async def run_service(db: DB):
    client = await get_reddit_client()
    asyncio.create_task(read_loop(client, db))
    asyncio.create_task(reply_loop(client, db))
    asyncio.create_task(post_loop(client, db))
    