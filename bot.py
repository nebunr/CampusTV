"""
Okay, I opened this, what do I do now? Let me help you.
Do you have python 3.5? Yes, good.
Open the terminal thingy and go to folder where all this is.
Put this stuff there:
    virtualenv env1 --python python3.5
    source env1/bin/activate
    pip install -r requirements.txt
    python run_once.py
After that, make sure DISCORD_TOKEN, TWITCH_ID, and CHANNEL_ID are properly filled in.
Now, make sure either stream_ids.txt and/or role_ids.txt have stuff in it.
Reminder, stream_ids.txt must have the ID, not Name (GamesDoneQuick 's ID is 22510310)
The _ids.txt must be separated by comma, no space, like so: 01234567,8901234
Done? now do:
    python bot.py
Congrats. Do some keyboard interrupt like ctrl+c to stop it.
When's it's all going, do NOT delete the messages it posts unless
you want to delete the logs and recreate message.db again. The bot
looks for that message ID and is sad if it can't find it.

Shoutouts Jawlecks and Tachyon.

Oh yeah, the permissions integer is: 116736
"""

#import constants # constants.py

import asyncio
import dataset
import datetime
import discord
import logging
from logging.handlers import TimedRotatingFileHandler
import os
import pytz
import sys
import twitch   # pip3 install python-twitch-client

DISCORD_STREAMING_TYPE = 1

MESSAGE_TEXT = '%s is live with %s, tune in now! %s'
OFFLINE_MESSAGE_TEXT = '**%s** is **offline**.'

EMBED_TYPE = 'rich'
EMBED_COLOR = 6570404

FOOTER_TEXT = 'Created by @jawlecks | Last updated'     # another shoutout going out to Jawlecks
FOOTER_ICON_URL = 'https://cdn.discordapp.com/emojis/328751425666547725.png'

AUTHOR_TEXT = '%s is now streaming!'
AUTHOR_OFFLINE_TEXT = '%s was streaming.'
AUTHOR_ICON_URL = 'https://cdn.discordapp.com/emojis/287637883022737418.png'

IMAGE_WIDTH = 400
IMAGE_HEIGHT = 225

DB_NAME = 'sqlite:///messages.db'   # default 'sqlite:///messages.db'
TABLE_NAME = 'message'              # default 'message'

STREAM_IDS_FILE = 'stream-ids-new.txt'  # default 'stream_ids.txt'
ROLE_IDS_FILE = 'role_ids.txt'      # default 'role_ids.txt'

POLL_INTERVAL = 1200    # seconds, default 1200 (20 minutes)

MAX_LOGS = 7    # default 7
LOG_DIR = 'logs/'
LOG_FILE = LOG_DIR + 'live-bot.log'

#DISCORD_TOKEN = constants.DISCORD_TOKEN
#TWITCH_ID = constants.TWITCH_ID
#CHANNEL_ID = constants.CHANNEL_ID
DISCORD_TOKEN = ''
TWITCH_ID = ''
CHANNEL_ID = discord.Object('')

class LiveBot():
    """Discord bot that posts when streams go live and updates with metadata."""

    def __init__(self):
        """Initialize the bot.

        Initialize logging and all clients. Get reference to event loop. Load
        stream and role id files.
        """
        self.logger = self.init_logger()

        self.loop = asyncio.get_event_loop()

        # initialize clients for discord, twitch, database
        self.discord = discord.Client(loop=self.loop)
        self.loop.run_until_complete(self.discord.login(DISCORD_TOKEN))
        self.twitch = twitch.TwitchClient(client_id=TWITCH_ID)
        self.db = dataset.connect(DB_NAME)
        self.table = self.db[TABLE_NAME]

        stream_ids = self.get_db_streams() +\
                     self.load_file(STREAM_IDS_FILE)
        self.stream_ids_map = {stream_id: None for stream_id in stream_ids}
        """
        dict of str to str or None: map of stream ids to discord display
        names or None if no discord account is linked to that stream.
        """

        #: list of str: list of role ids that members must have one or more of
        self.role_ids = self.load_file(ROLE_IDS_FILE)

        self.logger.debug('INITIALIZED')

    def init_logger(self):
        """Initialize log handler for discord, asyncio, and this class.

        Returns:
            logging.Logger: Logger for this class.
        """
        if not os.path.isdir(LOG_DIR):
            os.makedirs(LOG_DIR)

        formatter = logging.Formatter(
            '%(asctime)s:%(levelname)s:%(name)s: %(message)s')

        file_handler = TimedRotatingFileHandler(
            LOG_FILE,
            when='midnight',
            backupCount=MAX_LOGS,
            encoding='utf-8')
        file_handler.setFormatter(formatter)

        stdout_handler = logging.StreamHandler(sys.stdout)
        stdout_handler.setFormatter(formatter)

        discord_logger = logging.getLogger('discord')
        discord_logger.setLevel(logging.INFO)
        discord_logger.addHandler(file_handler)
        discord_logger.addHandler(stdout_handler)

        async_logger = logging.getLogger('asyncio')
        async_logger.setLevel(logging.INFO)
        async_logger.addHandler(file_handler)
        async_logger.addHandler(stdout_handler)

        logger = logging.getLogger('live-bot')
        logger.setLevel(logging.DEBUG)
        logger.addHandler(file_handler)
        logger.addHandler(stdout_handler)

        return logger

    def load_file(self, file):
        """Load contents of the given file.

        The file must contain comma-separated values.

        Args:
            file (str): The path to the file

        Returns:
            list: The values in the file or the empty list if the file was not
            found.
        """
        try:
            with open(file, 'r') as f:
                self.logger.info('File %s loaded' % file)
                return f.read().split(',')
        except FileNotFoundError:
            self.logger.info('File %s not found' % file)
            return []

    def write_file(self, file, data):
        """Write given contents to the given file.

        Args:
            file (str): The path to the file
            data (list): The data to write to the file
        """
        with open(file, 'w') as f:
            self.logger.info('Data saved to file {}: {}'.format(file, data))
            f.write(','.join(data))

    def run(self):
        """Run the bot.

        Create two tasks, one that listens to discord events and watches for
        users to start streaming, and one that polls twitch with all current
        stream ids at a set interval and sends/edits messages in discord. This
        function runs until it receives a KeyboardInterrupt.
        """
        try:
            tasks = [asyncio.ensure_future(self.listen()),
                     asyncio.ensure_future(self.poll())]
            self.loop.run_until_complete(asyncio.gather(*tasks))
        except KeyboardInterrupt:
            self.loop.run_until_complete(self.tear_down())
        finally:
            self.loop.close()

    async def listen(self):
        """Start listening to member update events from discord."""
        @self.discord.event
        async def on_member_update(before, after):
            """Callback for when a discord member update event is received.

            On member update, if the member was not streaming before and is now
            streaming their stream id is found and added to the stream id map
            with the value being their discord nickname or username.

            Args:
                before (discord.Member): The member before the update.
                after  (discord.Member): The member after the update.
            """
            if self.stream_change(before, after):
                self.logger.info('Discord Member %s started streaming' % after)
                user = after.game.url.split('/')[-1]
                ids = self.twitch.users.translate_usernames_to_ids([user])
                stream_id = str(ids[0].id)
                name = after.nick or after.name
                self.stream_ids_map[stream_id] = name

        # Start listening
        self.logger.debug('CONNECTING to discord')
        await self.discord.connect()

    def stream_change(self, before, after):
        """Return whether or not a member has started streaming.

        Args:
            before (discord.Member): The member before the update.
            after  (discord.Member): The member after the update.

        Retuns:
            True if the member started streaming, False otherwise.
        """
        return self.has_role(after)\
               and self.member_streaming(after)\
               and not self.member_streaming(before)

    def has_role(self, member):
        """Return whether or not the given member has any of the needed roles.

        Args:
            member (discord.Member): The member to check for roles.

        Returns:
            True if the member has any of the roles or if there are no roles,
            False otherwise.
        """
        if len(self.role_ids) == 0:
            return True

        for role in member.roles:
            if role.id in self.role_ids:
                return True

        return False

    def member_streaming(self, member):
        """Return whether or not the given member is currently streaming.

        Args:
            member (discord.Member): The member to check.

        Returns:
            True if the member is streaming, False otherwise.
        """
        return member.game is not None\
               and member.game.type == DISCORD_STREAMING_TYPE

    async def poll(self):
        """Poll twitch for live streams and update messages indefinitely.

        This function will run forever. Twitch is polled with all current stream
        ids and live streams are updated. Then the function sleeps for according
        to the poll interval and repeats.
        """
        while True:
            start = self.loop.time()
            await self.poll_once()
            sleep = POLL_INTERVAL - (self.loop.time() - start)
            self.logger.info('SLEEPING for %s seconds' % sleep)
            await asyncio.sleep(sleep)

    async def poll_once(self):
        """Polls twitch and updates discord messages for live/ended streams."""
        self.logger.info('POLLING')

        stream_ids = ','.join(self.stream_ids_map.keys())
        live_streams = self.twitch.streams.get_live_streams(channel=stream_ids, limit=100)
        live_stream_ids = [str(stream.channel.id) for stream in live_streams]
        db_streams = self.get_db_streams()
        print(live_stream_ids)
        self.logger.debug(live_stream_ids)
        self.logger.debug(db_streams)

        await self.update_live_streams(db_streams, live_streams)
        await self.update_ended_streams(db_streams, live_stream_ids)

    async def update_live_streams(self, db_streams, live_streams):
        """Start any streams that went live and update already live streams.

        If a stream id is in live_streams and db_streams it means we already
        posted a message to discord about it so we update that message with the
        current stream stats.

        If a stream id is in live_streams and not in db_streams that means it
        went live during the last sleep period so we post the first message for
        that stream.

        Args:
            db_streams (list of str): List of live streams we have already
                posted messages for.
            live_streams (list of twitch.Stream): List of streams currently live
                from twitch.
        """
        for stream in live_streams:
            stream_id = str(stream.channel.id)
            if stream_id in db_streams:
                message_id = self.get_message_id(stream_id)
                await self.update_stream(message_id, stream)
            else:
                await self.start_stream(stream, self.stream_ids_map[stream_id])

    async def update_ended_streams(self, db_streams, live_stream_ids):
        """Update messages for streams that ended.

        If a stream id is in db_streams and not live_streams that means it went
        offline during the last sleep period so we update the message to say the
        stream went offline and remove the stream from the database.

        Args:
            db_streams (list of str): List of live streams we have already
                posted messages for.
            live_stream_ids (list of str): List of stream ids currently live.
        """
        for stream_id in db_streams:
            if stream_id not in live_stream_ids:
                message_id = self.get_message_id(stream_id)
                await self.end_stream(message_id,
                                      self.stream_ids_map[stream_id])

    def get_db_streams(self):
        """list of str: All stream ids in the database."""
        return [str(row['stream_id']) for row in self.table.find()]

    def get_message_id(self, stream_id):
        """Get message id for the given stream id.

        Args:
            stream_id (str): The stream id.

        Returns:
            str: The message id associated with that stream id.
        """
        return self.table.find_one(stream_id=stream_id)['message_id']

    async def start_stream(self, stream: object, name: object) -> object:
        """Performs all actions associated with a stream going live.

        A message is sent to discord with the current stream metadata. A row is
        added to the database with the stream's id and the id of the message
        that was sent.

        Args:
            stream (twitch.Stream): The metadata for the stream.
            name (str): The user's discord name or None.
        """
        self.logger.debug('STARTING {}'.format(name))

        name = name or stream.channel.display_name
        content = MESSAGE_TEXT % (name,
                                            stream.channel.game,
                                            stream.channel.url)
        await asyncio.sleep(1)
        embed = await self.get_live_embed(stream)
        try:
            message = await self.discord.send_message(CHANNEL_ID, content=content, embed=embed)
        except:
            message = await self.discord.send_message(CHANNEL_ID, content=content)
        #im not screaming
        await asyncio.sleep(1)
        row = dict(message_id=message.id, stream_id=stream.channel.id)
        self.table.insert(row)

    async def update_stream(self, message_id, stream):
        """Updates the discord message with new stream metadata.

        Args:
            message_id (str): The message id of the message to edit.
            stream (twitch.Stream): The twitch stream metadata for the stream.
        """
        self.logger.debug('UPDATING {} ({})'
            .format(stream.channel.display_name, message_id))

        message = await self.get_message(message_id)
        embed = await self.get_live_embed(stream)
        await self.discord.edit_message(message,
                                        embed=embed)

    async def end_stream(self, message_id, name):
        """Performs all actions associated with a stream going offline.

        The discord message is edited one final time with an offline message.
        The message and associated stream id are removed from the database.

        Args:
            message_id (str): The message id of the message to edit.
            name (str): The username of the user who went offline or None.
        """
        self.logger.debug('ENDING {} ({})'.format(name, message_id))

        message = await self.get_message(message_id)
        stream_id = self.table.find_one(message_id=message_id)['stream_id']
        channel = self.twitch.channels.get_by_id(stream_id)

        name = name or channel.display_name
        content = OFFLINE_MESSAGE_TEXT % name
        embed = self.get_offline_embed(channel)
        await self.discord.edit_message(message,
                                        new_content=content,
                                        embed=embed)

        self.table.delete(message_id=message_id)

    async def get_message(self, message_id):
        """discord.Message: Return the message for the given message id."""
        print(CHANNEL_ID, message_id)
        return await self.discord.get_message(CHANNEL_ID, message_id)

    async def get_live_embed(self, stream):
        """Create the embed for the live stream message.

        Args:
            stream (twitch.Stream): The metadata for the stream.

        Returns:
            discord.Embed: The embed.
        """
        embed = self.get_base_embed(stream.channel,
                                    AUTHOR_TEXT)

        preview_url = stream.preview['template'].format(
            width=IMAGE_WIDTH,
            height=IMAGE_HEIGHT)
        image_url = preview_url
        embed.set_image(url=image_url)

        embed.add_field(name='Now Playing',
                        value=stream.game,
                        inline=False)
        embed.add_field(name='Stream Title',
                        value=stream.channel.status,
                        inline=False)
        embed.add_field(name='Current Viewers',
                        value=stream.viewers,
                        inline=True)
        embed.add_field(name='Followers',
                        value=stream.channel.followers,
                        inline=True)

        return embed

    def get_offline_embed(self, channel):
        """Create the embed for the offline stream message.

        Args:
            channel (twitch.Channel): The metadata for the channel.

        Returns:
            discord.Embed: The embed.
        """
        embed = self.get_base_embed(channel,
                                    AUTHOR_OFFLINE_TEXT)
        return embed

    def get_base_embed(self, channel, author_template):
        """Create the base embed for any message.

        Args:
            channel (twitch.Channel): The metadata for the channel.
            author_template (str): The string template to add the channel's
                name to.

        Returns:
            discord.Embed: The embed.
        """
        embed = discord.Embed(title=channel.url,
                              type=EMBED_TYPE,
                              url=channel.url,
                              timestamp=self.get_time(),
                              color=EMBED_COLOR)
        embed.set_thumbnail(url=channel.logo)
        embed.set_footer(text=FOOTER_TEXT,
                         icon_url=FOOTER_ICON_URL)
        embed.set_author(name=author_template % channel.display_name,
                         url=channel.url,
                         icon_url=AUTHOR_ICON_URL)
        return embed

    def get_time(self):
        """datetime.datetime: Return the time right now."""
        return datetime.datetime.now(pytz.timezone('US/Pacific'))

    async def tear_down(self):
        """Commit all changes to the database and disconnect from discord."""
        self.logger.debug('TEARING DOWN')
        self.write_file(STREAM_IDS_FILE, self.stream_ids_map.keys())
        self.db.commit()
        await self.discord.logout()


if __name__ == '__main__':
    lb = LiveBot()
    lb.run()
