# CampusTV

This is a Python 3 Discord bot where a livestream database is regularly updated to promote important information about Twitch streams in a Discord text channel.

To Start:
>     virtualenv env1 --python python3.6
>     source env1/bin/activate
>     pip3 install -r requirements.txt
>     python run_once.py
After that, make sure DISCORD_TOKEN, TWITCH_ID, and CHANNEL_ID are properly filled in.

Now, make sure either stream_ids.txt and/or role_ids.txt are properly filled in as well.

Reminder, stream_ids.txt must have the ID, not Name (GamesDoneQuick 's ID is 22510310)

The _ids.txt must be separated by comma, no space, like so: 01234567,8901234

To Run:
>     python bot.py

Congrats. Do some keyboard interrupt like ctrl+c to stop it.
When's it's all going, do NOT delete the messages it posts unless you want to delete the logs and recreate message.db again. The bot looks for that message ID and is sad if it can't find it.

The Discord permissions integer is: 116736 (0 works too if you have a role already setup for bots)

To invite the bot, use the URL below:
>     https://discordapp.com/oauth2/authorize?client_id=XXXXXXXXXXXXXXXXXX&scope=bot&permissions=X (replace Xs with id and the permission integer)

In case you break something or delete a message (which makes it sad). Remove the folders with:
>     rm messages.db
>     rm -r logs
Yeah that will kill the logs, so move those logs elsewhere if you want to keep them. After that, to run:
>     python run_once.py
>     python bot.py
