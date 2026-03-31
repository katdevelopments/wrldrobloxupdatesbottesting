import discord
from discord import app_commands
import requests
import json
import asyncio
import os
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
import collections
from typing import Optional
from discord.ext import tasks
import itertools
import coloredlogs

class NoPyNaClFilter(logging.Filter):
    def filter(self, record):
        return 'PyNaCl is not installed' not in record.getMessage()

class CustomFormatter(coloredlogs.ColoredFormatter):
    def format(self, record):
        return super().format(record)

coloredlogs.install(
    level='INFO',
    formatter_class=CustomFormatter,
    fmt='%(asctime)s %(levelname)-8s %(message)s',
    level_styles={
        'debug': {'color': 'cyan'},
        'info': {'color': 'green'},
        'warning': {'color': 'yellow'},
        'error': 'red',
        'critical': {'color': 'red', 'bold': True},
    },
    field_styles={
        'asctime': {'color': 'white', 'faint': True},
        'levelname': {'bold': True},
    }
)

logger = logging.getLogger('world_rblx_updates')
logger.setLevel(logging.INFO)

logging.getLogger('discord').setLevel(logging.WARNING)
logging.getLogger('discord.http').setLevel(logging.WARNING)
logging.getLogger('websockets').setLevel(logging.WARNING)

logging.getLogger('discord.voice_client').addFilter(NoPyNaClFilter())

SITE_URL = "https://useworld.xyz"
DISCORD_URL = "https://dsc.gg/globes"
DATA_PATH = "/var/data"
DB_FILE = os.path.join(DATA_PATH, 'bot_data.db')
ALL_DEVICES_LIST = ["windows", "mac", "android", "ios"]

BOT_COLOR = discord.Color.from_rgb(52, 152, 219)
SUCCESS_COLOR = discord.Color.from_rgb(46, 204, 113)
ERROR_COLOR = discord.Color.from_rgb(231, 76, 60)
WARN_COLOR = discord.Color.from_rgb(241, 196, 15)
INFO_COLOR = discord.Color.from_rgb(155, 89, 182)
CREDITS_COLOR = discord.Color.from_rgb(26, 188, 156)
DOWNGRADE_COLOR = discord.Color.from_rgb(230, 126, 34)
REVERT_COLOR = discord.Color.from_rgb(230, 126, 34)
IOS_DOWNLOAD_URL = "https://apps.apple.com/us/app/roblox/id431946152"
ANDROID_DOWNLOAD_URL = "https://play.google.com/store/apps/details?id=com.roblox.client"
PC_DOWNLOAD_URL = "https://www.roblox.com/download"

intents = discord.Intents.default()
bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)

start_time = None
announced_versions = {}

EST = timezone(timedelta(hours=-5))

STATUS_URL = "https://useworld.xyz"
status_list = [
    discord.Streaming(name="🔴 LIVE updates | useworld.xyz", url=STATUS_URL),
    discord.Activity(type=discord.ActivityType.watching, name="🛰️ for new builds | useworld.xyz"),
    discord.Activity(type=discord.ActivityType.playing, name="🎮 Spot the Update | useworld.xyz"),
    discord.Activity(type=discord.ActivityType.listening, name="📡 to the Roblox API | useworld.xyz"),
    discord.Streaming(name="🌎 World RBLX Updates | useworld.xyz", url=STATUS_URL),
    discord.Activity(type=discord.ActivityType.watching, name="💻📱 all platforms | useworld.xyz"),
    discord.Activity(type=discord.ActivityType.playing, name="🚀 with the latest builds | useworld.xyz"),
    discord.Streaming(name="⬇️ Get the latest | useworld.xyz", url=STATUS_URL),
    discord.Activity(type=discord.ActivityType.watching, name="👀 for the next drop | useworld.xyz"),
    discord.Streaming(name="⚡ Powering your updates | useworld.xyz", url=STATUS_URL),
    discord.Activity(type=discord.ActivityType.watching, name="📈 version changes | useworld.xyz"),
    discord.Activity(type=discord.ActivityType.playing, name="📁 Sorting build files | useworld.xyz"),
    discord.Streaming(name="🔔 Updates as they happen | useworld.xyz", url=STATUS_URL),
    discord.Activity(type=discord.ActivityType.listening, name="👂 for update pings | useworld.xyz"),
    discord.Activity(type=discord.ActivityType.watching, name="🛡️ useworld.xyz"),
]
status_cycle = itertools.cycle(status_list)

def setup_database():
    os.makedirs(DATA_PATH, exist_ok=True)
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS update_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT, device TEXT NOT NULL,
    version TEXT NOT NULL, timestamp TEXT NOT NULL
    )''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS server_configs (
    guild_id INTEGER PRIMARY KEY, channel_id INTEGER,
    enabled INTEGER NOT NULL DEFAULT 1, monitoring_devices TEXT,
    ping_roles TEXT
    )''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS subscriptions (
    user_id INTEGER NOT NULL, device TEXT NOT NULL,
    silent_dm INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, device)
    )''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS future_builds_history (
    device TEXT PRIMARY KEY,
    version TEXT NOT NULL
    )''')
    
    try: 
        cursor.execute("ALTER TABLE server_configs ADD COLUMN custom_messages TEXT")
    except sqlite3.OperationalError: pass
    try: 
        cursor.execute("ALTER TABLE server_configs ADD COLUMN silent_notifications INTEGER DEFAULT 0")
    except sqlite3.OperationalError: pass
    try: 
        cursor.execute("ALTER TABLE subscriptions ADD COLUMN silent_dm INTEGER NOT NULL DEFAULT 0")
    except sqlite3.OperationalError: pass
        
    conn.commit()
    conn.close()

def add_history_entry(device, version):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    timestamp = datetime.utcnow().isoformat()
    last_ver = get_latest_version_from_db(device)
    if version != last_ver:
        cursor.execute("INSERT INTO update_history (device, version, timestamp) VALUES (?, ?, ?)", (device, version, timestamp))
        cursor.execute ("DELETE FROM update_history WHERE id IN (SELECT id FROM update_history WHERE device = ? ORDER BY timestamp DESC LIMIT -1 OFFSET 10)", (device,))
        conn.commit()
    conn.close()

def get_latest_version_from_db(device):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT version FROM update_history WHERE device = ? ORDER BY timestamp DESC LIMIT 1", (device,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None

def check_if_version_in_history(device, version):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM update_history WHERE device = ? AND version = ? LIMIT 1", (device, version))
    row = cursor.fetchone()
    conn.close()
    return row is not None

def get_history(device, limit=10):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT timestamp, version FROM update_history WHERE device = ? ORDER BY timestamp DESC LIMIT ?", (device, limit))
    history = cursor.fetchall()
    conn.close()
    return [(datetime.fromisoformat(ts), ver) for ts, ver in history]

def get_announced_future_build(device):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT version FROM future_builds_history WHERE device = ?", (device,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None

def set_announced_future_build(device, version):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO future_builds_history (device, version) VALUES (?, ?)", (device, version))
    conn.commit()
    conn.close()

def get_server_config(guild_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM server_configs WHERE guild_id = ?", (guild_id,))
    row = cursor.fetchone()
    if row:
        columns = [description[0] for description in cursor.description]
        config_data = dict(zip(columns, row))
        config_data["enabled"] = bool(config_data.get("enabled", 1))
        config_data["silent_notifications"] = bool(config_data.get("silent_notifications", 0))
        config_data["monitoring_devices"] = json.loads(config_data.get("monitoring_devices") or '[]') or ALL_DEVICES_LIST
        config_data["ping_roles"] = json.loads(config_data.get("ping_roles") or '{}')
        config_data["custom_messages"] = json.loads(config_data.get("custom_messages") or '{}')
    else:
        cursor.execute("INSERT INTO server_configs (guild_id, monitoring_devices, ping_roles, custom_messages, silent_notifications) VALUES (?, ?, ?, ?, ?)",
                       (guild_id, json.dumps(ALL_DEVICES_LIST), json.dumps({}), json.dumps({}), 0))
        conn.commit()
        config_data = {"channel_id": None, "enabled": True, "monitoring_devices": ALL_DEVICES_LIST, "ping_roles": {}, "custom_messages": {}, "silent_notifications": False}
    conn.close()
    return config_data

def update_server_config(guild_id, key, value):
    if isinstance(value, (list, dict)):
        value = json.dumps(value)
    elif isinstance(value, bool): value = 1 if value else 0
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(f"UPDATE server_configs SET {key} = ? WHERE guild_id = ?", (value, guild_id))
    conn.commit()
    conn.close()

def add_subscription(user_id, device):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO subscriptions (user_id, device) VALUES (?, ?)", (user_id, device))
    conn.commit()
    conn.close()

def remove_subscription(user_id, device):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM subscriptions WHERE user_id = ? AND device = ?", (user_id, device))
    conn.commit()
    conn.close()
    return cursor.rowcount > 0

def get_user_subscriptions(user_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT device, silent_dm FROM subscriptions WHERE user_id = ?", (user_id,))
    subs = cursor.fetchall()
    conn.close()
    return subs

def set_user_silent_status(user_id, silent: bool):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE subscriptions SET silent_dm = ? WHERE user_id= ?", (1 if silent else 0, user_id))
    conn.commit()
    conn.close()

def get_subscribers_for_device(device):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM subscriptions WHERE device = ? AND silent_dm = 0", (device,))
    subscribers = [row[0] for row in cursor.fetchall()]
    conn.close()
    return subscribers

def get_download_link(device, version=None):
    if device == "windows" and version:
        return f"https://rdd.whatexpsare.online/?channel=LIVE&binaryType=WindowsPlayer&version={version.replace('version-', '')}"
    elif device == "mac" and version:
        return f"https://rdd.whatexpsare.online/?channel=LIVE&binaryType=MacPlayer&version={version.replace('version-','')}"
    elif device in ["windows", "mac"]:
        return PC_DOWNLOAD_URL
    elif device == "android":
        return ANDROID_DOWNLOAD_URL
    elif device == "ios":
        return IOS_DOWNLOAD_URL
    return None

def get_next_wednesday_release():
    now_est = datetime.now(EST)
    release_time = now_est.replace(hour=16, minute=30, second=0, microsecond=0)
    days_until_wednesday = (2 - now_est.weekday() + 7) % 7
    
    if days_until_wednesday == 0:
        if now_est >= release_time:
            release_date = now_est + timedelta(days=7)
        else:
            release_date = now_est
    else:
        release_date = now_est + timedelta(days=days_until_wednesday)
        
    next_release_datetime = release_date.replace(hour=16, minute=30, second=0, microsecond=0)
    return next_release_datetime

class UnsubscribeSelect(discord.ui.Select):
    def __init__(self, subscriptions):
        options = [discord.SelectOption(label="All Devices", value="all", emoji="\U0001F6AB")]
        options.extend([
            discord.SelectOption(
                label=dev[0].capitalize(), value=dev[0],
                emoji={"windows": "\U0001FA9F", "mac": "\U0001F34E", "android": "\U0001F916", "ios": "\U0001F4F1"}.get(dev[0])
            ) for dev in subscriptions
        ])
        super().__init__(
            placeholder="Select devices to unsubscribe from...",
            min_values=1,
            max_values=len(options),
            options=options
        )
    
    async def callback(self, interaction: discord.Interaction):
        devices_to_unsub = []
        unsubscribed_list_for_dm = []
        
        if "all" in self.values:
            all_user_subs = get_user_subscriptions(interaction.user.id)
            devices_to_unsub = [sub[0] for sub in all_user_subs]
            unsubscribed_list_for_dm = [sub[0].capitalize() for sub in all_user_subs]
        else:
            devices_to_unsub = self.values
            unsubscribed_list_for_dm = [dev.capitalize() for dev in self.values]
            
        unsubscribed_count = 0
        for device in devices_to_unsub:
            if remove_subscription(interaction.user.id, device):
                unsubscribed_count += 1
        
        await interaction.response.edit_message(content=f"✅ You have been unsubscribed from **{unsubscribed_count}** device(s). I've sent you a DM to confirm.", view=None)
        
        if unsubscribed_count > 0:
            try:
                device_list_str = "\n".join([f"• {dev}" for dev in unsubscribed_list_for_dm])
                embed = discord.Embed(
                    title="🚫 Unsubscribe Confirmation",
                    description=f"You have successfully unsubscribed from updates for the following devices:\n{device_list_str}",
                    color=SUCCESS_COLOR
                )
                await interaction.user.send(embed=embed)
            except discord.Forbidden:
                pass

class UnsubscribeSelectView(discord.ui.View):
    def __init__(self, user_id):
        super().__init__(timeout=180)
        subscriptions = get_user_subscriptions(user_id)
        if subscriptions:
            self.add_item(UnsubscribeSelect(subscriptions))

class SubscribeSelectView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
    
    @discord.ui.select(
        placeholder="Choose devices to get DMs for...",
        min_values=1,
        max_values=len(ALL_DEVICES_LIST) + 1
    )
    async def select_callback(self, interaction: discord.Interaction, select: discord.ui.Select):
        devices_to_sub = []
        if 'all' in select.values:
            devices_to_sub = ALL_DEVICES_LIST
        else:
            devices_to_sub = select.values
            
        for device in devices_to_sub:
            add_subscription(interaction.user.id, device)
            
        await interaction.response.edit_message(
            content=f"✅ Success! You are now subscribed. I've sent you a DM with your current subscription status.",
            view=None
        )
        
        try:
            subscriptions = get_user_subscriptions(interaction.user.id)
            device_list = "\n".join([f"• {dev[0].capitalize()}" for dev in subscriptions])
            embed = discord.Embed(
                title="📬 Your Roblox Update Subscriptions",
                description=f"You are currently subscribed to updates for the following devices:\n{device_list}\n\nUse `/unsubscribe` at any time to manage your subscriptions.",
                color=SUCCESS_COLOR
            )
            await interaction.user.send(embed=embed)
        except discord.Forbidden:
            pass

class InitialSubscribeView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        
    @discord.ui.button(label="Select Devices to Subscribe", style=discord.ButtonStyle.success, emoji="📩")
    async def select_devices(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="Please select the devices you want to get DMs for:",
            view=SubscribeSelectView()
        )

class SubscriptionPostView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        
    @discord.ui.button(label="Subscribe to DM Notifications", style=discord.ButtonStyle.primary, custom_id="persistent_subscribe_button", emoji="🔔")
    async def subscribe(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "Please select the devices you want to get DMs for:",
            view=SubscribeSelectView(),
            ephemeral=True
        )

async def get_device_version(device):
    if device == "android":
        url_32 = "https://clientsettingscdn.roblox.com/v2/client-version/AndroidApp"
        url_64 = "https://clientsettingscdn.roblox.com/v2/client-version/AndroidApp64"
        
        async def fetch(url):
            try:
                async with asyncio.timeout(10):
                    response = await asyncio.to_thread(requests.get, url)
                    if response.status_code == 200:
                        data = response.json()
                        return data.get("clientVersionUpload", data.get("version"))
            except:
                pass
            return None
            
        v32, v64 = await asyncio.gather(fetch(url_32), fetch(url_64))
        
        if v32 and v64 and v32 != v64:
            return f"ARM32: {v32} | ARM64: {v64}"
        elif v32:
            return v32
        elif v64:
            return v64
        return None
        
    binary_types = {
        "windows": "WindowsPlayer",
        "mac": "MacPlayer",
        "ios": "iOSApp"
    }
    binary_type = binary_types.get(device)
    if not binary_type: return None
    
    url = f"https://clientsettingscdn.roblox.com/v2/client-version/{binary_type}"
    try:
        async with asyncio.timeout(10):
            response = await asyncio.to_thread(requests.get, url)
            if response.status_code == 200:
                data = response.json()
                return data.get("clientVersionUpload", data.get("version"))
    except:
        pass
    return None

async def get_future_version(device):
    binary_types = {
        "windows": "WindowsPlayer",
        "mac": "MacPlayer"
    }
    binary_type = binary_types.get(device)
    if not binary_type: return None
    
    url = f"https://clientsettingscdn.roblox.com/v2/client-version/{binary_type}/channel/zfeature"
    try:
        async with asyncio.timeout(10):
            response = await asyncio.to_thread(requests.get, url)
            if response.status_code == 200:
                data = response.json()
                return data.get("clientVersionUpload", data.get("version"))
    except:
        pass
    return None

@tasks.loop(minutes=5)
async def change_bot_status():
    try:
        new_status = next(status_cycle)
        await bot.change_presence(activity=new_status, status=discord.Status.online)
    except:
        pass

@change_bot_status.before_loop
async def before_status_loop():
    await bot.wait_until_ready()

@bot.event
async def on_ready():
    global start_time
    start_time = datetime.utcnow()
    
    setup_database()
    
    bot.add_view(SubscriptionPostView())
    
    for device in ALL_DEVICES_LIST:
        latest_version = get_latest_version_from_db(device)
        if latest_version:
            announced_versions[device] = latest_version
            
    try:
        synced = await tree.sync()
    except:
        pass
        
    bot.loop.create_task(update_check_loop())
    change_bot_status.start()

async def check_for_live_updates():
    try:
        tasks = {
            "windows": get_device_version("windows"),
            "mac": get_device_version("mac"),
            "android": get_device_version("android"),
            "ios": get_device_version("ios")
        }
        
        devices_to_fetch = list(tasks.keys())
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)
        
        fetched_versions = {}
        for i, device in enumerate(devices_to_fetch):
            if isinstance(results[i], Exception):
                fetched_versions[device] = None
            else:
                fetched_versions[device] = results[i]
                
        new_updates_to_notify = {}
        reverted_updates_to_notify = {}
        downgraded_updates_to_notify = {}
        
        for device, current_version in fetched_versions.items():
            if not current_version or "Could not" in str(current_version):
                continue
                
            if "version-hidden" in current_version:
                continue
                
            last_announced = announced_versions.get(device)
            latest_db_version = get_latest_version_from_db(device)
            
            if current_version == last_announced:
                continue
                
            is_in_history = check_if_version_in_history(device, current_version)
            
            is_revert = False
            if latest_db_version and current_version != latest_db_version and is_in_history:
                is_revert = True
                
            if is_revert:
                reverted_updates_to_notify[device] = current_version
                announced_versions[device] = current_version
                add_history_entry(device, current_version)
                
            elif device in ['android', 'ios'] and not is_in_history and latest_db_version and current_version < latest_db_version:
                downgraded_updates_to_notify[device] = current_version
                announced_versions[device] = current_version
                add_history_entry(device, current_version)
                
            elif current_version != latest_db_version:
                add_history_entry(device, current_version)
                
                if last_announced is not None:
                    new_updates_to_notify[device] = current_version
                    
                announced_versions[device] = current_version
                
            elif current_version == latest_db_version:
                announced_versions[device] = current_version
        
        return new_updates_to_notify, reverted_updates_to_notify, downgraded_updates_to_notify
        
    except:
        return {}, {}, {}

async def check_for_future_builds(live_versions_map: dict):
    try:
        future_win, future_mac = await asyncio.gather(
            get_future_version("windows"),
            get_future_version("mac")
        )
        
        new_future_builds = {}
        
        live_win_version = live_versions_map.get("windows")
        if (future_win and 
            "version-placeholder" not in future_win and
            "version-hidden" not in future_win and
            future_win != get_announced_future_build("windows") and
            future_win != live_win_version):
            
            new_future_builds["windows"] = {"version": future_win, "date": datetime.utcnow().strftime("%Y-%m-%d")}
            set_announced_future_build("windows", future_win)
            
        live_mac_version = live_versions_map.get("mac")
        if (future_mac and 
            "version-placeholder" not in future_mac and
            "version-hidden" not in future_mac and
            future_mac != get_announced_future_build("mac") and
            future_mac != live_mac_version):
            
            new_future_builds["mac"] = {"version": future_mac, "date": datetime.utcnow().strftime("%Y-%m-%d")}
            set_announced_future_build("mac", future_mac)

        return new_future_builds
        
    except:
        return {}

async def update_check_loop():
    await bot.wait_until_ready()
    while not bot.is_closed():
        live_update_results = await check_for_live_updates()
        future_builds = await check_for_future_builds(announced_versions)
        live_updates, reverted_updates, downgraded_updates = live_update_results
        
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT guild_id, channel_id, monitoring_devices, ping_roles, custom_messages, silent_notifications FROM server_configs WHERE enabled = 1 AND channel_id IS NOT NULL")
        all_servers = cursor.fetchall()
        conn.close()
        
        if live_updates:
            for guild_id, channel_id, mon_dev_json, ping_roles_json, custom_msg_json, silent in all_servers:
                channel = bot.get_channel(channel_id)
                if not channel: continue
                
                mon_dev, ping_roles, custom_messages = json.loads(mon_dev_json or '[]'), json.loads(ping_roles_json or '{}'), json.loads(custom_msg_json or '{}')
                
                for device, current_version in live_updates.items():
                    if device in mon_dev:
                        role_id = ping_roles.get(device)
                        content = f"<@&{role_id}>" if role_id else ""
                        
                        custom_msg_template = custom_messages.get(device, custom_messages.get("all"))
                        
                        description = custom_msg_template.format(device=device.capitalize(), version=current_version, role=f"<@&{role_id}>" if role_id else "") if custom_msg_template else f"A new version of Roblox is rolling out for `{device.capitalize()}`!"
                        
                        emoji = {"windows": "\U0001FA9F", "mac": "\U0001F34E", "android": "\U0001F916", "ios": "\U0001F4F1"}.get(device, "🚀")
                        embed = discord.Embed(title=f"{emoji} Roblox ({device.capitalize()}) Update!", description=description, color=BOT_COLOR)
                        embed.add_field(name="Version", value=f"`{current_version}`", inline=False)
                        dl_url = get_download_link(device, current_version)
                        if dl_url: embed.add_field(name="Download Here", value=f"[Link]({dl_url})", inline=False)
                        embed.set_footer(text="World RBLX Updates").timestamp = discord.utils.utcnow()
                        
                        try: 
                            await channel.send(content=content, embed=embed, silent=bool(silent))
                        except:
                            pass
                        
            for device, current_version in live_updates.items():
                subscribers = get_subscribers_for_device(device)
                if subscribers:
                    emoji = {"windows": "\U0001FA9F", "mac": "\U0001F34E", "android": "\U0001F916", "ios": "\U0001F4F1"}.get(device, "🚀")
                    dm_embed = discord.Embed(title=f"{emoji} Roblox ({device.capitalize()}) Update", description=f"A new version is available: `{current_version}`", color=BOT_COLOR)
                    for user_id in subscribers:
                        try:
                            user = await bot.fetch_user(user_id)
                            await user.send(embed=dm_embed)
                        except:
                            pass
                            
        if reverted_updates:
            for guild_id, channel_id, mon_dev_json, _, _, silent in all_servers:
                channel = bot.get_channel(channel_id)
                if not channel: continue
                mon_dev = json.loads(mon_dev_json or '[]')
                for device, current_version in reverted_updates.items():
                    if device in mon_dev:
                        embed = discord.Embed(
                            title=f"↩️ Roblox Version Reverted ({device.capitalize()})",
                            description=f"Roblox appears to have reverted the version for `{device.capitalize()}` back to a previous build.",
                            color=REVERT_COLOR
                        )
                        embed.add_field(name="Now Detected Version", value=f"`{current_version}`", inline=False)
                        dl_url = get_download_link(device, current_version)
                        if dl_url: embed.add_field(name="Download Link (for this version)", value=f"[Link]({dl_url})", inline=False)
                        embed.set_footer(text="This version was previously released.")
                        try: 
                            await channel.send(embed=embed, silent=bool(silent))
                        except:
                            pass
                        
            for device, current_version in reverted_updates.items():
                subscribers = get_subscribers_for_device(device)
                if subscribers:
                    dm_embed = discord.Embed(title=f"↩️ Roblox ({device.capitalize()}) Version Reverted", description=f"The version has been reverted back to: `{current_version}`", color=REVERT_COLOR)
                    for user_id in subscribers:
                        try:
                            user = await bot.fetch_user(user_id)
                            await user.send(embed=dm_embed)
                        except:
                            pass
                            
        if downgraded_updates:
            for guild_id, channel_id, mon_dev_json, _, _, silent in all_servers:
                channel = bot.get_channel(channel_id)
                if not channel: continue
                mon_dev = json.loads(mon_dev_json or '[]')
                for device, current_version in downgraded_updates.items():
                    if device in mon_dev:
                        embed = discord.Embed(
                            title=f"📉 Roblox Version Downgraded ({device.capitalize()})",
                            description=f"Roblox appears to have rolled back the version for `{device.capitalize()}` to a previously unseen lower version.",
                            color=DOWNGRADE_COLOR
                        )
                        embed.add_field(name="Now Detected Version", value=f"`{current_version}`", inline=False)
                        dl_url = get_download_link(device, current_version)
                        if dl_url: embed.add_field(name="Download Link (for this version)", value=f"[Link]({dl_url})", inline=False)
                        embed.set_footer(text="This might be temporary or part of a phased rollout change.")
                        try: 
                            await channel.send(embed=embed, silent=bool(silent))
                        except:
                            pass
                        
            for device, current_version in downgraded_updates.items():
                subscribers = get_subscribers_for_device(device)
                if subscribers:
                    dm_embed = discord.Embed(title=f"📉 Roblox ({device.capitalize()}) Version Downgraded", description=f"The version has been unexpectedly downgraded to: `{current_version}`", color=DOWNGRADE_COLOR)
                    for user_id in subscribers:
                        try:
                            user = await bot.fetch_user(user_id)
                            await user.send(embed=dm_embed)
                        except:
                            pass
                            
        if future_builds:
            release_datetime = get_next_wednesday_release()
            release_timestamp = int(release_datetime.timestamp())

            for guild_id, channel_id, mon_dev_json, _, _, silent in all_servers:
                channel = bot.get_channel(channel_id)
                if not channel: continue
                
                mon_dev = json.loads(mon_dev_json or '[]')
                
                for device, data in future_builds.items():
                    if device in mon_dev:
                        emoji = {"windows": "\U0001FA9F", "mac": "\U0001F34E"}.get(device, "🔬")
                        embed = discord.Embed(title=f"{emoji} New Roblox Build Detected! ({device.capitalize()})", color=WARN_COLOR)
                        embed.add_field(name="Upcoming Version", value=f"`{data['version']}`", inline=False)
                        embed.add_field(name="Estimated Release", value=f"<t:{release_timestamp}:F> (<t:{release_timestamp}:R>)", inline=True)
                        
                        dl_link = get_download_link(device, data['version'])
                        if dl_link:
                            embed.add_field(name="Download Link", value=f"[Link]({dl_link})", inline=False)
                            
                        embed.set_footer(text="This build is not live yet. Release time is an estimate based on standard rollout patterns.")
                        
                        try:
                            await channel.send(embed=embed, silent=bool(silent))
                        except:
                            pass
            
        await asyncio.sleep(10)

@tree.command(name="ping", description="Pong!")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message(f"Pong! 🏓 Latency: `{round(bot.latency * 1000)}ms`")

@tree.command(name="uptime", description="Shows how long the bot has been online.")
async def uptime(interaction: discord.Interaction):
    if start_time:
        delta = datetime.utcnow() - start_time
        days, remainder = divmod(int(delta.total_seconds()), 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, seconds = divmod(remainder, 60)
        uptime_str = f"{days}d {hours}h {minutes}m {seconds}s"
        await interaction.response.send_message(f"I have been online for **{uptime_str}** ⏳.")
    else:
        await interaction.response.send_message("I've just started up, can't calculate uptime yet. ⏳", ephemeral=True)

@tree.command(name="help", description="Shows a list of all commands.")
async def help(interaction: discord.Interaction):
    embed= discord.Embed(title="❓ World RBLX Updates Help", color=INFO_COLOR, description="Here are all the available commands:")
    embed.add_field(name="🧭 General Commands", value="`/ping`, `/uptime`, `/site`, `/discord`, `/credits`, `/privacy`", inline=False)
    embed.add_field(name="📊 Update Information", value="`/check`, `/lastupdate`, `/history`, `/futurebuild`, `/pastupdate`, `/download`", inline=False)
    embed.add_field(name="🔔 Personal Notifications", value="`/subscribe`: Get DMs for new updates.\n`/unsubscribe`: Stop getting DMs for updates.\n`/silentnotifydm`: Toggle your DM notifications on or off.", inline=False)
    embed.add_field(name="🛠️ Server Configuration", value="`/subscribebutton`, `/config <...>`, `/updateping <...>`", inline=False)
    embed.set_footer(text="Use /subscribe to get started with DMs or click the button in a server!")
    await interaction.response.send_message(embed=embed, ephemeral=True)

@tree.command(name="privacy", description="Shows the bot's privacy policy.")
async def privacy(interaction: discord.Interaction):
    embed = discord.Embed(title="🔒 Privacy Policy", color=INFO_COLOR, description="This bot is designed with your privacy in mind. Here's what data is used and why:")
    embed.add_field(name="Server Data", value="Server ID, Channel ID, Role IDs for notifications.", inline=False)
    embed.add_field(name="User Data (DM Subscriptions)", value="User ID and chosen devices for DM notifications.", inline=False)
    embed.add_field(name="Command Usage", value="Command interactions are stateless.", inline=False)
    embed.set_footer(text="Your data is only used to provide the bot's core functionality.")
    await interaction.response.send_message(embed=embed, ephemeral=True)

@tree.command(name="site", description="Get the official website link.")
async def site(interaction: discord.Interaction):
    embed = discord.Embed(title="🌎 Official Site", description=f"[Click here to visit our website!]({SITE_URL})", color=BOT_COLOR)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@tree.command(name="discord", description="Get the official Discord server invite.")
async def discord_cmd(interaction: discord.Interaction):
    embed = discord.Embed(title="💬 Official Discord", description=f"[Click here to join the server!]({DISCORD_URL})", color=BOT_COLOR)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@tree.command(name="credits", description="Shows the bot's creators and developer.")
async def credits(interaction: discord.Interaction):
    embed= discord.Embed(title="🌟 Credits", color=CREDITS_COLOR)
    embed.add_field(name="Creators", value="World Works", inline=False)
    embed.add_field(name="Developer", value="<@1128435622076489748>", inline=False)
    embed.set_footer(text="Thank you for using World RBLX Updates!")
    await interaction.response.send_message(embed=embed, ephemeral=False)

@tree.command(name="check", description="Manually check the current version of a device.")
@app_commands.describe(device="The device to check the version for")
@app_commands.choices(device=[app_commands.Choice(name="All Devices", value="all")] + [app_commands.Choice(name=d.capitalize(), value=d) for d in ALL_DEVICES_LIST])
async def check(interaction: discord.Interaction, device: app_commands.Choice[str]):
    await interaction.response.defer()
    if device.value == "all":
        embed = discord.Embed(title="📊 Current Versions (All Devices)", color=BOT_COLOR)
        
        win, mac, android, ios = await asyncio.gather(
            get_device_version("windows"),
            get_device_version("mac"),
            get_device_version("android"),
            get_device_version("ios")
        )
        
        win_ver_str = f"`{win or 'Not found'}`"
        win_link = get_download_link("windows", win)
        embed.add_field(name="🪟 Windows", value=f"{win_ver_str} • [Download]({win_link})", inline=True)
        
        mac_ver_str = f"`{mac or 'Not found'}`"
        mac_link = get_download_link("mac", mac)
        embed.add_field(name="🍎 macOS", value=f"{mac_ver_str} • [Download]({mac_link})", inline=True)
        
        android_ver_str = f"`{android or 'Not found'}`"
        android_link = get_download_link("android")
        embed.add_field(name="🤖 Android", value=f"{android_ver_str} • [Download]({android_link})", inline=True)
        
        ios_ver_str = f"`{ios or 'Not found'}`"
        ios_link = get_download_link("ios")
        embed.add_field(name="📱 iOS", value=f"{ios_ver_str} • [Download]({ios_link})", inline=True)
        
        await interaction.followup.send(embed=embed)
        return
        
    version = await get_device_version(device.value)
    
    emoji = "❓"
    if device.value == "windows":
        emoji = "\U0001FA9F"
    elif device.value == "mac":
        emoji = "\U0001F34E"
    elif device.value == "android":
        emoji = "\U0001F916"
    elif device.value == "ios":
        emoji = "\U0001F4F1"
    
    dl_link = get_download_link(device.value, version)
    embed= discord.Embed(title=f"{emoji} Current Version {device.name}", color=BOT_COLOR)
    embed.add_field(name="Version", value=f"`{version or 'Not found'}`", inline=False)
    if dl_link: embed.add_field(name="Download", value=f"[Click Here]({dl_link})", inline=False)
    await interaction.followup.send(embed=embed)

@tree.command(name="lastupdate", description="Shows when the last update was detected for a device.")
@app_commands.describe(device="The device to check")
@app_commands.choices(device=[app_commands.Choice(name="All Devices", value="all")] + [app_commands.Choice(name=d.capitalize(), value=d) for d in ALL_DEVICES_LIST])
async def last_update(interaction: discord.Interaction, device: app_commands.Choice[str]):
    if device.value == "all":
        embed = discord.Embed(title="🕓 Last Updates (All Devices)", color=BOT_COLOR)
        for dev_name in ALL_DEVICES_LIST:
            history = get_history(dev_name)
            value = f"`{history[0][1]}`\n<t:{int(history[0][0].timestamp())}:R>" if history else " No updates recorded."
            emoji = {"windows": "\U0001FA9F", "mac": "\U0001F34E", "android": "\U0001F916", "ios": "\U0001F4F1"}.get(dev_name, "")
            embed.add_field(name=f"{emoji} {dev_name.capitalize()}", value=value, inline=True)
        await interaction.response.send_message(embed=embed)
        return
        
    history = get_history(device.value)
    if not history: return await interaction.response.send_message(f"I haven't recorded any updates for **{device.name}** yet.", ephemeral=True)
    
    ts, ver = history[0]
    dl_link = get_download_link(device.value, ver)
    emoji = {"windows": "\U0001FA9F", "mac": "\U0001F34E", "android": "\U0001F916", "ios": "\U0001F4F1"}.get(device.value, "🕓")
    embed = discord.Embed(title=f"{emoji} Last Update {device.name}", color=BOT_COLOR)
    embed.add_field(name="Version", value=f"`{ver}`", inline=False).add_field(name="Detected", value=f"<t:{int(ts.timestamp())}:R>", inline=False)
    if dl_link: embed.add_field(name="Download", value=f"[Click Here]({dl_link})", inline=False)
    await interaction.response.send_message(embed=embed)

@tree.command(name="history", description="Shows the last 10 detected updates for a device.")
@app_commands.describe(device="The device to check")
@app_commands.choices(device=[app_commands.Choice(name=d.capitalize(), value=d) for d in ALL_DEVICES_LIST])
async def history(interaction: discord.Interaction, device: app_commands.Choice[str]):
    history_data = get_history(device.value)
    if not history_data:
        return await interaction.response.send_message(f"I don't have any update history for **{device.name}**.", ephemeral=True)
        
    emoji = {"windows": "\U0001FA9F", "mac": "\U0001F34E", "android": "\U0001F916", "ios": "\U0001F4F1"}.get(device.value, "📜")
    embed= discord.Embed(title=f"{emoji} Update History {device.name}", color=BOT_COLOR)
    description_lines = []
    for ts, ver in history_data:
        dl_link = get_download_link(device.value, ver)
        if dl_link and "rdd" in dl_link:
            description_lines.append(f"<t:{int(ts.timestamp())}:f>: `{ver}` ([Download]({dl_link}))")
        else:
            description_lines.append(f"<t:{int(ts.timestamp())}:f>: `{ver}`")
            
    embed.description = "\n".join(description_lines)
    await interaction.response.send_message(embed=embed)

@tree.command(name="futurebuild", description="Checks for the next upcoming Roblox build.")
async def futurebuild(interaction: discord.Interaction):
    await interaction.response.defer()
    
    future_win, future_mac, live_win, live_mac = await asyncio.gather(
        get_future_version("windows"),
        get_future_version("mac"),
        get_device_version("windows"),
        get_device_version("mac")
    )
    
    embed = discord.Embed(title="🔭 Upcoming Roblox Builds", color=WARN_COLOR)
    no_new_builds = True
    
    release_datetime = get_next_wednesday_release()
    release_timestamp = int(release_datetime.timestamp())
    
    if future_win and "version-placeholder" not in future_win and "version-hidden" not in future_win and future_win != live_win:
        no_new_builds = False
        dl_link = get_download_link("windows", future_win)
        embed.add_field(name="🪟 Windows", 
                        value=f"**Version:** `{future_win}`\n**Est. Release:** <t:{release_timestamp}:R>\n[Download]({dl_link})", 
                        inline=False)
        
    if future_mac and "version-placeholder" not in future_mac and "version-hidden" not in future_mac and future_mac != live_mac:
        no_new_builds = False
        dl_link = get_download_link("mac", future_mac)
        embed.add_field(name="🍎 macOS", 
                        value=f"**Version:** `{future_mac}`\n**Est. Release:** <t:{release_timestamp}:R>\n[Download]({dl_link})", 
                        inline=False)
        
    if no_new_builds:
        embed.description = "There are no new upcoming builds for Roblox at the moment. The current versions are live."
        embed.color = SUCCESS_COLOR
    else:
        embed.set_footer(text="Release time is an estimate based on standard rollout patterns.")
        
    await interaction.followup.send(embed=embed)

@tree.command(name="pastupdate", description="Shows the last known released build of Roblox.")
async def pastupdate(interaction: discord.Interaction):
    await interaction.response.defer()
    
    embed = discord.Embed(title="⏮️ Last Released Roblox Builds", color=BOT_COLOR)
    
    for device in ["windows", "mac"]:
        history = get_history(device, limit=2)
        if len(history) >= 2:
            ts, past_ver = history[1]
            dl_link = get_download_link(device, past_ver)
            emoji = "\U0001FA9F" if device == "windows" else "\U0001F34E"
            embed.add_field(name=f"{emoji} {device.capitalize()}", value=f"**Version:** `{past_ver}`\n**Detected:** <t:{int(ts.timestamp())}:f>\n[Download]({dl_link})", inline=True)
        else:
            emoji = "\U0001FA9F" if device == "windows" else "\U0001F34E"
            embed.add_field(name=f"{emoji} {device.capitalize()}", value="*No past updates found.*", inline=True)
            
    embed.add_field(name="\u200b", value="\u200b", inline=False)
    
    for device in ["android", "ios"]:
        history = get_history(device, limit=2)
        if len(history) >= 2:
            ts, past_ver = history[1]
            emoji = "\U0001F916" if device == "android" else "\U0001F4F1"
            embed.add_field(name=f"{emoji} {device.capitalize()}", value=f"**Last Seen:** `{past_ver}`\n**Detected:** <t:{int(ts.timestamp())}:f>\n*Downloads not available.*", inline=True)
        else:
            emoji = "\U0001F916" if device == "android" else "\U0001F4F1"
            embed.add_field(name=f"{emoji} {device.capitalize()}", value="*No past updates found.*", inline=True)
    
    await interaction.followup.send(embed=embed)

@tree.command(name="download", description="Get a direct download link for a specific Roblox version.")
@app_commands.describe(device="The device to download for", version="The version hash (e.g., version-xxxxxxxxx)")
@app_commands.choices(device=[
    app_commands.Choice(name="Windows", value="windows"),
    app_commands.Choice(name="macOS", value="mac"),
])
async def download(interaction: discord.Interaction, device: app_commands.Choice[str], version: str):
    dl_link = get_download_link(device.value, version)
    if not dl_link or "rdd" not in dl_link:
        await interaction.response.send_message(embed=discord.Embed(description="Could not generate a download link. Make sure the version hash is correct.", color=ERROR_COLOR), ephemeral=True)
        return
        
    emoji = "\U0001FA9F" if device.value == "windows" else "\U0001F34E"
    embed = discord.Embed(title=f"{emoji} Download for {device.name}", color=SUCCESS_COLOR, description=f"Click the link below to download version `{version}`.")
    embed.add_field(name="Download Link", value=f"[Click Here]({dl_link})")
    await interaction.response.send_message(embed=embed, ephemeral=True)

@tree.command(name="subscribe", description="Subscribe to get DMs for new device updates.")
async def subscribe(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🔔 Subscribe to World RBLX Updates?",
        description="Click the button below to select which devices you'd like to receive DM notifications for.",
        color=BOT_COLOR
    )
    await interaction.response.send_message(embed=embed, view=InitialSubscribeView(), ephemeral=True)

@tree.command(name="unsubscribe", description="Unsubscribe from device update DMs.")
async def unsubscribe(interaction: discord.Interaction):
    subscriptions = get_user_subscriptions(interaction.user.id)
    if not subscriptions:
        await interaction.response.send_message(embed=discord.Embed(description="You aren't subscribed to any device updates.", color=WARN_COLOR), ephemeral=True)
        return
    await interaction.response.send_message(
        "Please select the devices you wish to unsubscribe from:",
        view=UnsubscribeSelectView(interaction.user.id),
        ephemeral=True
    )

@tree.command(name="silentnotifydm", description="Toggle your DM notifications on or off.")
async def silentnotifydm(interaction: discord.Interaction):
    subscriptions = get_user_subscriptions(interaction.user.id)
    if not subscriptions:
        await interaction.response.send_message(embed=discord.Embed(description="You are not subscribed to any devices. Use `/subscribe` to get started.", color=WARN_COLOR), ephemeral=True)
        return
        
    is_currently_silent = any(sub[1] == 1 for sub in subscriptions)
    new_status = not is_currently_silent
    set_user_silent_status(interaction.user.id, new_status)
    
    status_text = "DISABLED 🔕" if new_status else "ENABLED 🔔"
    color = ERROR_COLOR if new_status else SUCCESS_COLOR
    embed = discord.Embed(description=f"Your DM notifications for all subscribed devices are now **{status_text}**.", color=color)
    await interaction.response.send_message(embed=embed, ephemeral=True)

class DeviceNotifierSelect(discord.ui.Select):
    def __init__(self, current_devices):
        options = []
        for d in ALL_DEVICES_LIST:
            options.append(discord.SelectOption(
                label=d.capitalize(), value=d,
                emoji={"windows": "\U0001FA9F", "mac": "\U0001F34E", "android": "\U0001F916", "ios": "\U0001F4F1"}.get(d),
                default=d in current_devices
            ))
            
        super().__init__(
            placeholder="Choose devices to notify in this channel...",
            min_values=0,
            max_values=len(ALL_DEVICES_LIST),
            options=options,
            custom_id="device_notifier_select"
        )
        
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        selected_devices = self.values or []
        update_server_config(interaction.guild.id, "monitoring_devices", selected_devices)
        await interaction.edit_original_response(content=f"✅ Success! This channel will now receive notifications for: `{', '.join(selected_devices) or 'None'}`.", view=None)

class DeviceNotifierSelectView(discord.ui.View):
    def __init__(self, current_devices):
        super().__init__(timeout=180)
        self.add_item(DeviceNotifierSelect(current_devices))

def has_admin():
    async def predicate(interaction: discord.Interaction) -> bool:
        if not interaction.guild:
            await interaction.response.send_message(embed=discord.Embed(description="This command must be used in a server.", color=ERROR_COLOR), ephemeral=True)
            return False
        if interaction.user.guild_permissions.administrator:
            return True
        await interaction.response.send_message(embed=discord.Embed(description="You need **Administrator** permission to use this command.", color=ERROR_COLOR), ephemeral=True)
        return False
    return app_commands.check(predicate)

@tree.command(name="subscribebutton", description="Posts a button for members to subscribe to DM notifications.")
@has_admin()
async def post_subscribe_button(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🔔 Get Notified of Roblox Updates!",
        description="Click the button below to subscribe to personal notifications in your DMs whenever Roblox releases a new update for your chosen devices.",
        color=BOT_COLOR
    )
    await interaction.channel.send(embed=embed, view=SubscriptionPostView())
    await interaction.response.send_message("✅ Subscription button posted!", ephemeral=True)

config_group = app_commands.Group(name="config", description="Configure bot settings for this server.", guild_only=True)

@config_group.command(name="channel", description="Sets the channel for update notifications.")
@has_admin()
async def set_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    update_server_config(interaction.guild.id, "channel_id", channel.id)
    await interaction.response.send_message(embed=discord.Embed(description=f"✅ Success! Update channel set to {channel.mention}.", color=SUCCESS_COLOR), ephemeral=True)

@config_group.command(name="toggle", description="Enables or disables the update checker for this server.")
@has_admin()
async def toggle_checker(interaction: discord.Interaction):
    server_config = get_server_config(interaction.guild.id)
    new_status = not server_config.get("enabled", True)
    update_server_config(interaction.guild.id, "enabled", new_status)
    status = "ENABLED 💡" if new_status else "DISABLED 🚫"
    await interaction.response.send_message(embed=discord.Embed(description=f"The update checker is now **{status}** for this server.", color=SUCCESS_COLOR), ephemeral=True)

@config_group.command(name="testnotice", description="Sends a test update notification to your configured channel.")
@app_commands.choices(device=[app_commands.Choice(name="All Devices", value="all")] + [app_commands.Choice(name=d.capitalize(), value=d) for d in ALL_DEVICES_LIST])
@has_admin()
async def test_notice(interaction: discord.Interaction, device: app_commands.Choice[str]):
    await interaction.response.defer(ephemeral=True)
    server_config = get_server_config(interaction.guild.id)
    if not server_config.get("channel_id"): 
        return await interaction.followup.send(embed=discord.Embed(description="❌ **Error:** No update channel configured.", color=ERROR_COLOR))
    channel = bot.get_channel(server_config["channel_id"])
    if not channel: 
        return await interaction.followup.send(embed=discord.Embed(description="❌ **Error:** I can't find the configured channel.", color=ERROR_COLOR))
    
    device_name = "All Devices" if device.value == "all" else device.name
    embed = discord.Embed(title=f"🧪 Test Notification ({device_name})", description="This is a test to ensure notifications are working correctly.", color=WARN_COLOR)
    embed.add_field(name="Version", value="`version-test-12345`", inline=False).set_footer(text=f"Test triggered by {interaction.user.display_name}")
    
    try:
        await channel.send(embed=embed)
        await interaction.followup.send(embed=discord.Embed(description=f"✅ Test notice sent to {channel.mention}!", color=SUCCESS_COLOR))
    except:
        await interaction.followup.send(embed=discord.Embed(description=f"❌ **Error:** I don't have permission to send messages in {channel.mention}.", color=ERROR_COLOR))

@config_group.command(name="custommessage", description="Set a custom notification message for your server.")
@app_commands.choices(device=[app_commands.Choice(name="All Devices", value="all")] + [app_commands.Choice(name=d.capitalize(), value=d) for d in ALL_DEVICES_LIST])
@has_admin()
async def set_custom_message(interaction: discord.Interaction, device: app_commands.Choice[str], message: str):
    server_config = get_server_config(interaction.guild.id)
    custom_messages = server_config.get("custom_messages", {})
    custom_messages[device.value] = message
    update_server_config(interaction.guild.id, "custom_messages", custom_messages)
    
    embed = discord.Embed(title="✅ Custom Message Set!", color=SUCCESS_COLOR)
    embed.description = f"The message for **{device.name}** is now:\n>>> {message}"
    embed.set_footer(text="Variables: {device}, {version}, {role}")
    await interaction.response.send_message(embed=embed, ephemeral=True)

@config_group.command(name="silentnotice", description="Toggle silent notifications for this server.")
@has_admin()
async def toggle_silent_notice(interaction: discord.Interaction, silent: bool):
    update_server_config(interaction.guild.id, "silent_notifications", silent)
    status = "ON 🔕 (Notifications will not make a sound)" if silent else "OFF 🔔 (Notifications will make a sound)"
    await interaction.response.send_message(embed=discord.Embed(description=f"Toggled silent notifications **{status}**.", color=SUCCESS_COLOR), ephemeral=True)

@config_group.command(name="view", description="Views the current bot configuration for this server.")
@has_admin()
async def view_config(interaction: discord.Interaction):
    server_config = get_server_config(interaction.guild.id)
    channel = bot.get_channel(server_config.get("channel_id", 0))
    embed= discord.Embed(title=f"⚙️ Configuration for {interaction.guild.name}", color=INFO_COLOR)
    embed.add_field(name="Status", value=" Enabled 💡" if server_config.get("enabled") else " Disabled 🚫", inline=False)
    embed.add_field(name=" Notification Channel", value=channel.mention if channel else "`Not Set`", inline=False)
    embed.add_field(name=" Devices Notified", value=f"`{', '.join(server_config.get('monitoring_devices', []))}`", inline=False)
    embed.add_field(name=" Silent Notifications", value=" On 🔕" if server_config.get("silent_notifications") else " Off 🔔", inline=False)
    custom_messages = server_config.get("custom_messages", {})
    msg_str = "\n".join([f"**{k.capitalize()}**: `{v}`" for k, v in custom_messages.items()]) or "`Default`"
    embed.add_field(name=" Custom Messages", value=msg_str, inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@config_group.command(name="devicenotifiers", description="Choose which devices trigger notifications in the server channel.")
@has_admin()
async def set_device_notifiers(interaction: discord.Interaction):
    server_config = get_server_config(interaction.guild.id)
    current_devices = server_config.get("monitoring_devices", ALL_DEVICES_LIST)
    await interaction.response.send_message("Please select the devices you want this channel to receive notifications for:",
                                            view=DeviceNotifierSelectView(current_devices), ephemeral=True)

tree.add_command(config_group)

updateping_group = app_commands.Group(name="updateping", description="Configure role pings for this server.", guild_only=True)

@updateping_group.command(name="set", description="Set or clear a role to be pinged for a specific device.")
@app_commands.describe(device="The device to set/clear the ping role for.", role="The role to ping (leave blank to clear).")
@app_commands.choices(device=[app_commands.Choice(name="All Devices", value="all")] + [app_commands.Choice(name=d.capitalize(), value=d) for d in ALL_DEVICES_LIST])
@has_admin()
async def set_ping(interaction: discord.Interaction, device: app_commands.Choice[str], role: Optional[discord.Role] = None):
    server_config = get_server_config(interaction.guild.id)
    ping_roles = server_config.get("ping_roles", {})
    devices_to_modify = ALL_DEVICES_LIST if device.value == "all" else [device.value]
    
    if role:
        for d in devices_to_modify:
            ping_roles[d] = role.id
        role_mention = role.mention
        device_name = "All Devices" if device.value == "all" else device.name
        message = f"✅ The {role_mention} role will now be pinged for **{device_name}** updates."
        color = SUCCESS_COLOR
    else:
        cleared_count = 0
        for d in devices_to_modify:
            if ping_roles.pop(d, None):
                cleared_count += 1
                
        device_name = "All Devices" if device.value == "all" else device.name
        if cleared_count > 0:
            message = f"✅ Cleared ping role(s) for **{device_name}**."
            color = SUCCESS_COLOR
        else:
            message = f"⚠️ No ping role was set for **{device_name}**."
            color = WARN_COLOR
            
    update_server_config(interaction.guild.id, "ping_roles", ping_roles)
    await interaction.response.send_message(embed=discord.Embed(description=message, color=color), ephemeral=True)

@updateping_group.command(name="view", description="View the current role ping configuration.")
@has_admin()
async def view_pings(interaction: discord.Interaction):
    server_config = get_server_config(interaction.guild.id)
    embed = discord.Embed(title=f"📣 Role Pings for {interaction.guild.name}", color=INFO_COLOR)
    ping_roles = server_config.get("ping_roles", {})
    description = "\n".join([f"**{d.capitalize()}**: {f'<@&{ping_roles.get(d)}>' if ping_roles.get(d) else '`Not Set`'}" for d in ALL_DEVICES_LIST])
    embed.description = description or "No ping roles are configured."
    await interaction.response.send_message(embed=embed, ephemeral=True)

tree.add_command(updateping_group)

bot_token = os.environ.get('DISCORD_BOT_TOKEN')
if bot_token:
    try:
        bot.run(bot_token)
    except:
        pass
