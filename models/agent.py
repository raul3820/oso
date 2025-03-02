import os
import asyncio
import logfire
from models import replier, summarizer, leeloo_dallas, pic
from db.func import DBFunctions as DB
from db.struct import MsgClassification, MsgSource

check_every_seconds = int(os.getenv("CHECK_EVERY_SECONDS", 300))

async def classify_msgs(db: DB) -> bool:
    """Classifies msgs using lilo_dallas.multi_pass."""
    
    try:
        ex = [MsgClassification.illegal, MsgClassification.banned, MsgClassification.instruction]
        
        if os.getenv('TEST_MODE') == 'True':
            ex = []
        
        locked_msgs = await db.get_locked_msgs_to_classify(ex)

        if not locked_msgs:
            logfire.info("No msgs to classify.")
            return True

        tasks = [leeloo_dallas.multi_pass(msg.body) for msg in locked_msgs]
        classifications = await asyncio.gather(*tasks, return_exceptions=True)

        msgs_to_upsert = []
        for msg, classification in zip(locked_msgs, classifications):
            if not classification:
                continue # Skip this msg if classification failed.

            msg.classification = classification
            msgs_to_upsert.append(msg)

        if not msgs_to_upsert:
            logfire.error("No msgs were successfully classified.")
            return False
        
        r = await db.update_msgs(msgs_to_upsert)
        await db.release_locks(locked_msgs)
        
        return r
        
    except Exception as e:
        logfire.exception(f"An unexpected error occurred during msg classification: {e}")
        return False

async def generate_replies(db: DB) -> bool:
    """Generates a response to unreplied msgs and updates the database."""

    any = [MsgClassification.inquiry, MsgClassification.boring, MsgClassification.spam, MsgClassification.other]
    ex = [MsgClassification.illegal, MsgClassification.banned, MsgClassification.instruction]

    if os.getenv('TEST_MODE') == 'True':
        any.extend(ex)
        ex = []

    locked_msgs = await db.get_locked_msgs_to_reply(any, ex)
    
    if not locked_msgs:
        logfire.info("No threads to reply to.")
        return True

    tasks = [db.get_thread_of_msgs(msg) for msg in locked_msgs]
    msg_threads = await asyncio.gather(*tasks)
    
    if not msg_threads:
        logfire.error("No msgs found in the fetched threads.")
        return False

    tasks = [replier.generate_response(msgs) for msgs in msg_threads]
    replies = await asyncio.gather(*tasks)
    
    if not replies:
        logfire.error(f"Error generating replies.")
        return False

    msgs = [msgs[-1] for msgs in msg_threads]

    msgs_to_update = []
    for msg, reply in zip(msgs, replies):
        if not reply:
            continue
        
        msg.reply_body = reply
        msgs_to_update.append(msg)

    if not msgs_to_update:
        logfire.error(f"No valid replies generated.")
        return False

    r = await db.update_msgs(msgs)
    await db.release_locks(locked_msgs)

    return r
    
async def generate_summaries(db: DB) -> bool:
    """Generates stories based on the given prompt with error handling."""
    any = [MsgClassification.story]
    ex = [MsgClassification.banned, MsgClassification.instruction]

    if os.getenv('TEST_MODE') == 'True':
        ex = []

    locked_msgs = await db.get_locked_msgs_to_summarize(any, ex)
    
    if not locked_msgs:
        logfire.info("No msgs found to summarize.")
        return True

    tasks = [summarizer.generate_response(msg.body) for msg in locked_msgs]
    summaries = await asyncio.gather(*tasks, return_exceptions=True)
    if not summaries:
        logfire.error(f"Error gathering summaries.")
        return False

    msgs_to_update = []
    for msg, summary in zip(locked_msgs, summaries):
        if not summary:
            continue
        prefix = ""
        if msg.source in [MsgSource.RedditChat, MsgSource.RedditComment, MsgSource.RedditMessage]:
            prefix = 'u/'
        elif msg.source in [MsgSource.TwitterComment, MsgSource.TwitterMessage]:
            prefix = '@'

        image = pic.get_image_bytes(summary + f"\n\n -- {prefix}{msg.receiver})")
        if not image:
            continue

        msg.summary = summary
        msg.images = [image]
        msgs_to_update.append(msg)
    
    if not msgs_to_update:
        logfire.error("No valid summaries generated.")
        return False


    r = await db.update_msgs(msgs_to_update)
    await db.release_locks(locked_msgs)
    
    return r

async def run_agent_pipeline_service(db: DB):
    """Task for agents to process msgs in the DB."""

    async def loop(db: DB):
        """Runs the msg processing pipeline in a loop with specified interval."""
        while True:
            try:
                await classify_msgs(db)
                await generate_replies(db)
                await generate_summaries(db)
                await asyncio.sleep(check_every_seconds)
            except asyncio.CancelledError:
                logfire.info("Agent pipeline service cancelled, exiting loop.")
                break
            except Exception as e:
                logfire.exception(f"An error occurred in msg pipeline loop: {e}")
                await asyncio.sleep(check_every_seconds)

    task = asyncio.create_task(loop(db))
    return task