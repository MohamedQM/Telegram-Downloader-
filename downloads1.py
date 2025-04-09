import os
import re
import subprocess
import logging
import time
import json
import shutil
import sqlite3
import sys
from typing import List, Tuple, Dict, Optional, Any, Union

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('bot_output.log')
    ]
)
logger = logging.getLogger(__name__)

logger.info(f"Python version: {sys.version}")
logger.info(f"Current directory: {os.getcwd()}")

# Directly import required packages (for PythonAnywhere compatibility)
from dotenv import load_dotenv
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
import yt_dlp

# Load environment variables from .env file
try:
    load_dotenv()
    logger.info("Successfully loaded environment variables")
except Exception as e:
    logger.error(f"Failed to load environment variables: {e}")

# --- Configuration ---
# تحديث توكن البوت على التوكن الجديد
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', 'TELEGRAM_BOT_TOKEN')
# Hardcode token if needed for testing
if not TOKEN:
    TOKEN = "TELEGRAM_BOT_TOKEN"
    
DOWNLOAD_DIR = 'downloads'
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB - Telegram bot API limit
ADMIN_ID = os.getenv('ADMIN_ID', 'ADMIN_ID')  # Admin user ID to receive notifications
DB_PATH = 'bot_users.db'  # SQLite database path
CONFIG_PATH = 'bot_config.json'  # Configuration file path
CHANNEL_USERNAME = "bad_wolf_01"  # Channel username without @ (required for subscription)
CHANNEL_LINK = "https://t.me/bad_wolf_01"  # Full channel link for invitation
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Load admin ID from config file if it exists
def load_config():
    """Load configuration from file."""
    global ADMIN_ID
    try:
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, 'r') as f:
                config = json.load(f)
                ADMIN_ID = config.get('admin_id', ADMIN_ID)
    except Exception as e:
        logger.error(f"Error loading config: {e}")

def save_config(admin_id=None):
    """Save configuration to file."""
    try:
        config = {}
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, 'r') as f:
                config = json.load(f)
        
        if admin_id:
            config['admin_id'] = admin_id
            global ADMIN_ID
            ADMIN_ID = admin_id
        
        with open(CONFIG_PATH, 'w') as f:
            json.dump(config, f)
        
        return True
    except Exception as e:
        logger.error(f"Error saving config: {e}")
        return False

# Load configuration
load_config()

# We've already configured logging, no need to do it again

# --- Helper Functions ---
def is_valid_url(text: str) -> bool:
    """Check if the given text is a valid URL."""
    url_pattern = re.compile(r'^https?://\S+$')
    return bool(url_pattern.match(text))

def clean_url(url: str) -> str:
    """Remove query parameters and fragments from URL."""
    return re.sub(r'[?#].*$', '', url)

def detect_platform(url: str) -> str:
    """Detect the platform from the URL."""
    u = url.lower()
    if 'spotify.com' in u:       return 'Spotify'
    if 'youtube.com' in u or 'youtu.be' in u: return 'YouTube'
    if 'facebook.com' in u or 'fb.com' in u:  return 'Facebook'
    if 'instagram.com' in u:     return 'Instagram'
    if 'tiktok.com' in u:        return 'TikTok'
    if 'soundcloud.com' in u:    return 'SoundCloud'
    if 'twitter.com' in u or 'x.com' in u:    return 'Twitter'
    if 'snapchat.com' in u:      return 'Snapchat'
    if 'vimeo.com' in u:         return 'Vimeo'
    if 'reddit.com' in u:        return 'Reddit'
    if 'twitch.tv' in u:         return 'Twitch'
    return 'Unknown'

def is_youtube_playlist(url: str) -> bool:
    """Check if URL is a YouTube playlist."""
    return 'youtube.com/playlist' in url.lower() or 'list=' in url.lower()

def get_quality_options(platform: str) -> Dict[str, str]:
    """Get quality options based on platform."""
    if platform in ['YouTube', 'Facebook', 'Vimeo']:
        return {
            'high': 'High Quality (1080p)',
            'medium': 'Medium Quality (720p)',
            'low': 'Low Quality (480p)',
            'audio': 'Audio Only (MP3)'
        }
    elif platform in ['Instagram', 'TikTok', 'Twitter']:
        return {
            'best': 'Best Quality',
            'audio': 'Audio Only (MP3)'
        }
    elif platform in ['SoundCloud', 'Spotify']:
        return {
            'best': 'Best Quality Audio'
        }
    else:
        return {
            'best': 'Best Quality',
            'audio': 'Audio Only (MP3)'
        }

def get_ydl_opts(url: str, quality: str = 'best') -> Tuple[Dict[str, Any], bool]:
    """Get yt-dlp options based on URL and quality."""
    platform = detect_platform(url)
    is_audio = quality == 'audio' or platform in ['SoundCloud', 'Spotify']
    
    common = {
        'outtmpl': os.path.join(DOWNLOAD_DIR, '%(title)s.%(ext)s'),
        'quiet': False,  # Enable verbose output for debugging
        'verbose': True, # More verbose for troubleshooting
        'no_warnings': False,
        'socket_timeout': 120,  # Increased timeout
        'nocheckcertificate': True,
        'ignoreerrors': False,  # Don't ignore errors to see what's happening
        'noplaylist': False,    # Allow downloading playlists
        'http_headers': {
            'User-Agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/121.0.0.0 Safari/537.36'
            ),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'cross-site'
        }
    }
    
    # Platform-specific settings
    if 'tiktok.com' in url.lower():
        # Special TikTok settings to bypass restrictions
        common['http_headers'].update({
            'Referer': 'https://www.tiktok.com/',
            'Cookie': 'tt_webid_v2=randomhash; tt_webid=randomhash; ttwid=randomhash;'
        })
        # Additional TikTok options
        common.update({
            'extractor_args': {
                'tiktok': {
                    'embed_protocol': 'm3u8_native',
                    'test_socks5': 'localhost:0'  # Dummy value to trigger certain behavior
                }
            }
        })
    
    # YouTube-specific options
    if 'youtube.com' in url.lower() or 'youtu.be' in url.lower():
        # Add additional YouTube-specific options
        common.update({
            'extract_flat': 'in_playlist',
            'skip_download': False,
            'cookiefile': None,  # No cookies needed
            'age_limit': 0,      # Don't restrict by age
        })
    
    # Quality settings
    if is_audio:
        return {
            **common,
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
        }, True
    else:
        format_str = 'bestvideo+bestaudio/best'
        if quality == 'high':
            format_str = 'bestvideo[height<=1080]+bestaudio/best[height<=1080]/best'
        elif quality == 'medium':
            format_str = 'bestvideo[height<=720]+bestaudio/best[height<=720]/best'
        elif quality == 'low':
            format_str = 'bestvideo[height<=480]+bestaudio/best[height<=480]/best'
        
        return {
            **common,
            'format': format_str,
            'merge_output_format': 'mp4'
        }, False

def download_media(url: str, quality: str = 'best') -> List[Tuple[str, bool]]:
    """Download media using yt-dlp."""
    opts, is_audio = get_ydl_opts(url, quality)
    logger.info(f"Starting download with yt-dlp for URL: {url}, quality: {quality}")
    
    try:
        # Clean the download directory first to avoid confusion with existing files
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)
        
        with yt_dlp.YoutubeDL(opts) as ydl:
            try:
                info = ydl.extract_info(url, download=True)
                if not info:
                    logger.error("No information extracted from URL")
                    return []
                
                # Handle single video or playlist
                entries = []
                if 'entries' in info:
                    # It's a playlist
                    entries = [entry for entry in info['entries'] if entry]
                    logger.info(f"Found playlist with {len(entries)} items")
                else:
                    # It's a single video
                    entries = [info]
                    logger.info("Found single video")
                
                files = []
                for entry in entries:
                    if entry is None:
                        continue
                    
                    # Get the prepared filename
                    if isinstance(entry, dict):
                        filename = None
                        
                        # Try to get the filename using different methods
                        try:
                            # Method 1: Use prepare_filename if id and ext are available
                            if 'id' in entry and 'ext' in entry:
                                path = ydl.prepare_filename(entry)
                                filename = path
                        except Exception as e:
                            logger.error(f"Error preparing filename: {str(e)}")
                        
                        # Method 2: Check if the file was already saved
                        if not filename or not os.path.exists(filename):
                            if 'title' in entry:
                                # Look for files with similar names in the download directory
                                title = entry['title']
                                for fname in os.listdir(DOWNLOAD_DIR):
                                    if title.lower() in fname.lower():
                                        filename = os.path.join(DOWNLOAD_DIR, fname)
                                        break
                        
                        # Process the file if found
                        if filename and os.path.exists(filename):
                            # For audio downloads, check if MP3 conversion worked
                            if is_audio and not filename.endswith('.mp3'):
                                mp3_path = os.path.splitext(filename)[0] + '.mp3'
                                if os.path.exists(mp3_path):
                                    filename = mp3_path
                            
                            files.append((filename, is_audio))
                            logger.info(f"Added file to results: {filename}")
                
                # If no files were found using the above methods, look for any new media files
                if not files:
                    logger.info("No files found through direct methods, scanning directory...")
                    # Look for media files in the download directory
                    for fname in os.listdir(DOWNLOAD_DIR):
                        if fname.lower().endswith(('.mp4', '.mkv', '.mp3', '.m4a', '.wav', '.webm')):
                            path = os.path.join(DOWNLOAD_DIR, fname)
                            # Determine if it's audio based on extension
                            is_audio_file = fname.lower().endswith(('.mp3', '.m4a', '.wav'))
                            files.append((path, is_audio_file or is_audio))
                            logger.info(f"Found media file: {path}")
                
                return files
                
            except Exception as e:
                logger.error(f"Error in yt-dlp extraction: {str(e)}")
                raise
    except Exception as e:
        logger.error(f"Error in download_media: {str(e)}")
        raise Exception(f"Failed to download: {str(e)}")

def download_spotify(url: str) -> List[Tuple[str, bool]]:
    """Download Spotify tracks using spotdl."""
    try:
        cmd = ['spotdl', url, '--output', DOWNLOAD_DIR]
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        files = []
        for fname in os.listdir(DOWNLOAD_DIR):
            if fname.lower().endswith(('.mp3', '.m4a')):
                files.append((os.path.join(DOWNLOAD_DIR, fname), True))
        return files
    except subprocess.CalledProcessError as e:
        logger.error(f"spotdl error: {e}")
        logger.error(f"stdout: {e.stdout.decode() if e.stdout else 'None'}")
        logger.error(f"stderr: {e.stderr.decode() if e.stderr else 'None'}")
        raise Exception("Failed to download from Spotify. Make sure spotdl is installed and working properly.")

def split_large_file(file_path: str) -> List[str]:
    """Split large files into smaller chunks for Telegram."""
    file_size = os.path.getsize(file_path)
    if file_size <= MAX_FILE_SIZE:
        return [file_path]
    
    base_name, ext = os.path.splitext(file_path)
    chunk_size = MAX_FILE_SIZE
    chunks = []
    
    # For videos, use ffmpeg to split
    if ext.lower() in ['.mp4', '.avi', '.mkv', '.mov']:
        duration_cmd = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', 
                        '-of', 'default=noprint_wrappers=1:nokey=1', file_path]
        duration = float(subprocess.check_output(duration_cmd).decode().strip())
        
        # Calculate segment duration based on file size
        segment_duration = int((chunk_size / file_size) * duration)
        if segment_duration < 1:
            segment_duration = 1
            
        for i in range(0, int(duration), segment_duration):
            chunk_path = f"{base_name}_part{i//segment_duration + 1}{ext}"
            cmd = ['ffmpeg', '-ss', str(i), '-t', str(segment_duration), '-i', file_path, 
                   '-c', 'copy', chunk_path]
            subprocess.run(cmd, check=True)
            chunks.append(chunk_path)
    
    # For audio, use direct binary splitting
    elif ext.lower() in ['.mp3', '.m4a', '.wav']:
        with open(file_path, 'rb') as f:
            data = f.read()
        
        total_chunks = (file_size + chunk_size - 1) // chunk_size
        for i in range(total_chunks):
            chunk_path = f"{base_name}_part{i+1}{ext}"
            with open(chunk_path, 'wb') as f:
                start = i * chunk_size
                end = min((i + 1) * chunk_size, file_size)
                f.write(data[start:end])
            chunks.append(chunk_path)
    
    return chunks

# --- Command and Message Handlers ---
async def check_channel_subscription(user_id: int) -> bool:
    """Check if user is subscribed to the required channel."""
    try:
        bot = Bot(TOKEN)
        member = await bot.get_chat_member(f"@{CHANNEL_USERNAME}", user_id)
        subscription_status = member.status
        # Consider administrators, creators, and members as subscribed
        return subscription_status in ['member', 'administrator', 'creator']
    except Exception as e:
        logger.error(f"Error checking subscription: {e}")
        # If there's an error checking, we'll consider them not subscribed to be safe
        return False

async def get_subscription_keyboard():
    """Get keyboard with subscription button."""
    keyboard = [
        [InlineKeyboardButton("✨ اشترك في القناة ✨", url=CHANNEL_LINK)],
        [InlineKeyboardButton("✅ تم الاشتراك (التحقق)", callback_data="check_subscription")]
    ]
    return InlineKeyboardMarkup(keyboard)

async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    # Track user in database and notify admin about new users
    user = update.effective_user
    is_new_user = add_user_to_db(
        user.id, 
        user.username, 
        user.first_name, 
        user.last_name
    )
    
    # If it's a new user, notify admin
    if is_new_user:
        await notify_admin_about_new_user(context, user)
    
    # Check if user is subscribed to the channel
    is_subscribed = await check_channel_subscription(user.id)
    
    if not is_subscribed:
        # Ask user to subscribe first
        await update.message.reply_text(
            f"👋 مرحبًا {user.first_name}! 🎉\n\n"
            "⚠️ يجب عليك الاشتراك في قناتنا أولاً للاستمرار في استخدام البوت.\n\n"
            "1️⃣ اضغط على زر \"اشترك في القناة\" أدناه\n"
            "2️⃣ بعد الاشتراك، عد واضغط على \"تم الاشتراك (التحقق)\"\n\n"
            "شكراً لدعمك! 🙏",
            reply_markup=await get_subscription_keyboard()
        )
        return
    
    # User is subscribed, show welcome message
    await update.message.reply_text(
        f"👋 مرحبًا {user.first_name}! 🎉\n\n"
        "🎬 أرسل لي رابط من أي منصة لتحميله:\n"
        "▪️ YouTube\n▪️ Facebook\n▪️ Instagram\n▪️ TikTok\n"
        "▪️ Twitter (X)\n▪️ SoundCloud\n▪️ Spotify\n▪️ Snapchat\n\n"
        "🔍 يمكنك تحميل فيديوهات أو مقاطع صوتية بجودات مختلفة.\n"
        "📚 يدعم البوت تحميل قوائم التشغيل والألبومات.\n\n"
        "/help - لمزيد من المعلومات والمساعدة"
    )

async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command."""
    await update.message.reply_text(
        "📋 *كيفية استخدام البوت:*\n\n"
        "1️⃣ أرسل رابط من أي منصة مدعومة\n"
        "2️⃣ اختر جودة التحميل (إن توفرت)\n"
        "3️⃣ انتظر حتى يتم التحميل وإرسال الملف\n\n"
        "*المنصات المدعومة:*\n"
        "▪️ YouTube - فيديوهات وقوائم تشغيل\n"
        "▪️ Facebook - فيديوهات عامة\n"
        "▪️ Instagram - منشورات وقصص وريلز\n"
        "▪️ TikTok - فيديوهات\n"
        "▪️ Twitter (X) - تغريدات بفيديو\n"
        "▪️ SoundCloud - مقاطع صوتية وألبومات\n"
        "▪️ Spotify - أغاني وألبومات وقوائم تشغيل\n"
        "▪️ Snapchat - قصص عامة\n\n"
        "*ملاحظات:*\n"
        "▪️ حجم الملف الأقصى: 50 ميغابايت\n"
        "▪️ الملفات الكبيرة يتم تقسيمها تلقائيًا\n"
        "▪️ بعض المحتوى المحمي قد لا يمكن تحميله\n\n"
        "/start - للعودة للبداية\n"
        "/formats - لعرض جودات التحميل المدعومة",
        parse_mode="Markdown"
    )

async def formats_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /formats command."""
    await update.message.reply_text(
        "🎞 *جودات التحميل المدعومة:*\n\n"
        "*للفيديو:*\n"
        "▪️ عالية: 1080p (Full HD)\n"
        "▪️ متوسطة: 720p (HD)\n"
        "▪️ منخفضة: 480p (SD)\n"
        "▪️ صوت فقط: MP3\n\n"
        "*للمقاطع الصوتية:*\n"
        "▪️ MP3 بجودة 192kbps\n\n"
        "*ملاحظة:* قد لا تتوفر بعض الجودات حسب المنصة والمحتوى.",
        parse_mode="Markdown"
    )

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming message with URL."""
    # Check if user is subscribed to the channel first
    user_id = update.effective_user.id
    is_subscribed = await check_channel_subscription(user_id)
    
    if not is_subscribed:
        await update.message.reply_text(
            "⚠️ يجب عليك الاشتراك في قناتنا أولاً للاستمرار في استخدام البوت.",
            reply_markup=await get_subscription_keyboard()
        )
        return
    
    # Process the URL
    text = update.message.text.strip()
    if not is_valid_url(text):
        await update.message.reply_text("❌ يرجى إرسال رابط صالح فقط.")
        return
    
    url = clean_url(text)
    platform = detect_platform(url)
    is_playlist = is_youtube_playlist(url)
    
    # If it's a YouTube playlist, inform the user
    if is_playlist:
        await update.message.reply_text(
            "🔄 تم اكتشاف قائمة تشغيل YouTube. سأقوم بتحميل جميع الفيديوهات في القائمة.\n"
            "⚠️ قد يستغرق هذا بعض الوقت حسب عدد الفيديوهات."
        )
    
    # Get quality options based on platform
    options = get_quality_options(platform)
    
    # If we have multiple quality options, show inline keyboard
    if len(options) > 1:
        buttons = []
        for quality, label in options.items():
            # Create a unique but short callback data
            # Format: dl|platform|quality|urlhash
            url_hash = str(abs(hash(url)) % 10000000)
            callback_data = f"dl|{platform[:3]}|{quality}|{url_hash}"
            
            # Store the URL in context
            if not context.bot_data.get('urls'):
                context.bot_data['urls'] = {}
            context.bot_data['urls'][url_hash] = url
            
            buttons.append([InlineKeyboardButton(label, callback_data=callback_data)])
            
        markup = InlineKeyboardMarkup(buttons)
        await update.message.reply_text(f"🔍 اختر جودة التحميل من {platform}:", reply_markup=markup)
    else:
        # For platforms with only one quality option, proceed directly
        quality = list(options.keys())[0]
        msg = await update.message.reply_text(f"⏳ جارٍ التحميل من {platform}...")
        await process_download(update, msg, url, quality)

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle callback queries from inline keyboards."""
    query = update.callback_query
    data = query.data.split('|')
    
    # Handle verification of channel subscription
    if data[0] == "check_subscription":
        is_subscribed = await check_channel_subscription(query.from_user.id)
        if is_subscribed:
            await query.edit_message_text(
                "✅ تم التحقق من اشتراكك!\n\n"
                "🎬 يمكنك الآن استخدام البوت بالكامل.\n"
                "أرسل أي رابط فيديو أو صوت للتحميل."
            )
        else:
            await query.answer("لم يتم العثور على اشتراكك في القناة. يرجى الاشتراك أولاً.", show_alert=True)
    
    # Handle download requests
    elif data[0] == "dl":
        platform = data[1]
        quality = data[2]
        url_hash = data[3]
        
        # Verify user is subscribed
        is_subscribed = await check_channel_subscription(query.from_user.id)
        if not is_subscribed:
            await query.answer("يجب عليك الاشتراك في القناة أولاً!", show_alert=True)
            await query.edit_message_text(
                "⚠️ يجب عليك الاشتراك في قناتنا أولاً للاستمرار.",
                reply_markup=await get_subscription_keyboard()
            )
            return
        
        # Get the URL from context
        url = context.bot_data.get('urls', {}).get(url_hash)
        if not url:
            await query.answer("خطأ: لم يتم العثور على الرابط. يرجى إعادة إرسال الرابط.", show_alert=True)
            return
        
        # Acknowledge the callback query
        await query.answer()
        
        # Update message to show progress
        msg = await query.edit_message_text(f"⏳ جارٍ التحميل... 0%")
        
        # Process the download
        await process_download(update, msg, url, quality)

async def process_download(update: Update, message, url: str, quality: str = 'best'):
    """Process the download and send files to user."""
    try:
        # Update progress message
        await message.edit_text("⏳ جاري التحميل والمعالجة...")
        
        # Download based on platform
        if 'spotify.com' in url.lower():
            try:
                files = download_spotify(url)
            except Exception as e:
                await message.edit_text(f"❌ فشل تحميل Spotify: {str(e)}")
                return
        else:
            try:
                files = download_media(url, quality)
            except Exception as e:
                await message.edit_text(f"❌ فشل التحميل: {str(e)}")
                return
        
        if not files:
            await message.edit_text("❌ لم يتم العثور على محتوى للتحميل.")
            return
        
        # Update progress
        await message.edit_text(f"✅ اكتمل التحميل! جارٍ الإرسال ({len(files)} ملف)...")
        
        # Send each file
        sent_count = 0
        for file_path, is_audio in files:
            # Skip non-existent files
            if not os.path.exists(file_path):
                continue
                
            # Get file size
            file_size = os.path.getsize(file_path)
            filename = os.path.basename(file_path)
            
            # Handle large files - split if needed
            if file_size > MAX_FILE_SIZE:
                await message.edit_text(f"📦 تقسيم الملف الكبير: {filename}")
                chunks = split_large_file(file_path)
                
                for i, chunk in enumerate(chunks):
                    chunk_name = os.path.basename(chunk)
                    status = await send_file(update, chunk, is_audio, f"جزء {i+1}/{len(chunks)} - {filename}")
                    if status:
                        sent_count += 1
                    # Clean up chunk
                    if os.path.exists(chunk):
                        os.remove(chunk)
            else:
                # Send regular sized file
                status = await send_file(update, file_path, is_audio, filename)
                if status:
                    sent_count += 1
            
            # Clean up original file
            if os.path.exists(file_path):
                os.remove(file_path)
        
        # Final status message
        if sent_count > 0:
            await message.edit_text(f"✅ تم إرسال {sent_count} ملف بنجاح!")
        else:
            await message.edit_text("❌ لم يتم إرسال أي ملف.")
            
    except Exception as e:
        logger.error(f"Error in process_download: {str(e)}")
        await message.edit_text(f"❌ حدث خطأ: {str(e)}")

async def send_file(update: Update, file_path: str, is_audio: bool, caption: str) -> bool:
    """Send file to user as appropriate type."""
    try:
        # Get the chat to send to
        chat_id = update.effective_chat.id
        
        if is_audio:
            # Send as audio file
            with open(file_path, 'rb') as f:
                await update.effective_chat.send_audio(
                    audio=f,
                    caption=caption[:1024],  # Telegram caption limit
                    title=os.path.splitext(caption)[0][:64],  # Telegram title limit
                    performer="Downloaded by Downloader Bot"
                )
        else:
            # Determine file type by extension
            ext = os.path.splitext(file_path)[1].lower()
            
            if ext in ['.mp4', '.avi', '.mov', '.mkv']:
                # Send as video
                with open(file_path, 'rb') as f:
                    try:
                        await update.effective_chat.send_video(
                            video=f,
                            caption=caption[:1024]
                        )
                    except Exception:
                        # If failed, try as document
                        with open(file_path, 'rb') as f2:
                            await update.effective_chat.send_document(
                                document=f2,
                                caption=caption[:1024]
                            )
            else:
                # Send as generic document
                with open(file_path, 'rb') as f:
                    await update.effective_chat.send_document(
                        document=f,
                        caption=caption[:1024]
                    )
        return True
    except Exception as e:
        logger.error(f"Error sending file: {e}")
        try:
            await update.effective_chat.send_message(f"❌ فشل إرسال الملف: {caption}")
        except:
            pass
        return False

# --- Database Functions ---
def init_database():
    """Initialize SQLite database for user tracking."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Create users table if not exists
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            join_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        
        # Create downloads table if not exists
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS downloads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            platform TEXT,
            url TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
        ''')
        
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Database initialization error: {e}")

def add_user_to_db(user_id, username, first_name, last_name):
    """Add new user to database. Returns True if new user, False if existing."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Check if user exists
        cursor.execute("SELECT id FROM users WHERE id = ?", (user_id,))
        existing = cursor.fetchone()
        
        if not existing:
            # Add new user
            cursor.execute(
                "INSERT INTO users (id, username, first_name, last_name) VALUES (?, ?, ?, ?)",
                (user_id, username, first_name, last_name)
            )
            conn.commit()
            conn.close()
            return True  # New user
        
        conn.close()
        return False  # Existing user
    except Exception as e:
        logger.error(f"Error adding user to database: {e}")
        return False

def record_download(user_id, platform, url):
    """Record download in database."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute(
            "INSERT INTO downloads (user_id, platform, url) VALUES (?, ?, ?)",
            (user_id, platform, url)
        )
        
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Error recording download: {e}")

def get_user_stats():
    """Get user statistics from database."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Total users
        cursor.execute("SELECT COUNT(*) FROM users")
        total_users = cursor.fetchone()[0]
        
        # Total downloads
        cursor.execute("SELECT COUNT(*) FROM downloads")
        total_downloads = cursor.fetchone()[0]
        
        # Downloads per platform
        cursor.execute("SELECT platform, COUNT(*) FROM downloads GROUP BY platform")
        platform_stats = cursor.fetchall()
        
        # Recent users
        cursor.execute("SELECT id, username, first_name, join_date FROM users ORDER BY join_date DESC LIMIT 5")
        recent_users = cursor.fetchall()
        
        conn.close()
        
        return {
            "total_users": total_users,
            "total_downloads": total_downloads,
            "platform_stats": platform_stats,
            "recent_users": recent_users
        }
    except Exception as e:
        logger.error(f"Error getting user stats: {e}")
        return {
            "total_users": 0,
            "total_downloads": 0,
            "platform_stats": [],
            "recent_users": []
        }

async def notify_admin_about_new_user(context, user):
    """Send notification to admin about new user."""
    if not ADMIN_ID:
        return
    
    try:
        # Get stats
        stats = get_user_stats()
        
        # Format user info
        user_info = (
            f"👤 <b>مستخدم جديد!</b>\n\n"
            f"• <b>الاسم:</b> {user.first_name} {user.last_name or ''}\n"
            f"• <b>المعرف:</b> @{user.username or 'لا يوجد'}\n"
            f"• <b>الرقم:</b> <code>{user.id}</code>\n\n"
            f"📊 <b>إجمالي المستخدمين:</b> {stats['total_users']}"
        )
        
        # Create inline keyboard with user profile link
        keyboard = []
        if user.username:
            keyboard.append([InlineKeyboardButton("👤 فتح الملف الشخصي", url=f"https://t.me/{user.username}")])
            
        # Add direct message button
        keyboard.append([InlineKeyboardButton("💬 مراسلة", url=f"tg://user?id={user.id}")])
        
        markup = InlineKeyboardMarkup(keyboard)
        
        # Send notification to admin
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=user_info,
            parse_mode="HTML",
            reply_markup=markup
        )
    except Exception as e:
        logger.error(f"Error notifying admin: {e}")

async def stats_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /stats command to show statistics."""
    user_id = update.effective_user.id
    
    # Only allow admin to view stats
    if str(user_id) != str(ADMIN_ID):
        await update.message.reply_text("⛔️ هذا الأمر متاح للمسؤول فقط.")
        return
    
    # Get stats from database
    stats = get_user_stats()
    
    # Format platform stats
    platform_text = ""
    for platform, count in stats["platform_stats"]:
        platform_text += f"• {platform}: {count}\n"
    
    if not platform_text:
        platform_text = "• لا توجد بيانات بعد\n"
    
    # Format recent users
    users_text = ""
    for uid, username, name, date in stats["recent_users"]:
        user_display = f"@{username}" if username else name
        users_text += f"• {user_display} - {uid}\n"
    
    if not users_text:
        users_text = "• لا يوجد مستخدمين بعد\n"
    
    # Compose message
    message = (
        "📊 <b>إحصائيات البوت</b>\n\n"
        f"👥 <b>إجمالي المستخدمين:</b> {stats['total_users']}\n"
        f"📥 <b>إجمالي التنزيلات:</b> {stats['total_downloads']}\n\n"
        "<b>التنزيلات حسب المنصة:</b>\n"
        f"{platform_text}\n"
        "<b>آخر المستخدمين:</b>\n"
        f"{users_text}"
    )
    
    await update.message.reply_text(message, parse_mode="HTML")

async def admin_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /admin command to set or update admin ID."""
    user_id = update.effective_user.id
    user_id_str = str(user_id)
    
    # Check if command has arguments
    args = context.args
    
    # If no arguments, show current admin or set self as admin
    if not args:
        if ADMIN_ID:
            if user_id_str == ADMIN_ID:
                await update.message.reply_text(f"✅ أنت المسؤول الحالي للبوت.\n\nلتعيين مسؤول جديد، استخدم:\n/admin <معرف المستخدم الجديد>")
            else:
                await update.message.reply_text("⛔️ أنت لست المسؤول. فقط المسؤول الحالي يمكنه تغيير الإعدادات.")
        else:
            # No admin set, set current user
            if save_config(user_id_str):
                await update.message.reply_text("✅ تم تعيينك كمسؤول للبوت! يمكنك الآن استخدام أوامر المسؤول.")
            else:
                await update.message.reply_text("❌ حدث خطأ أثناء تعيين المسؤول.")
        return
    
    # Only current admin can change admin
    if ADMIN_ID and user_id_str != ADMIN_ID:
        await update.message.reply_text("⛔️ فقط المسؤول الحالي يمكنه تغيير المسؤول.")
        return
    
    # Set new admin ID
    new_admin_id = args[0]
    if save_config(new_admin_id):
        await update.message.reply_text(f"✅ تم تعيين المستخدم {new_admin_id} كمسؤول جديد.")
    else:
        await update.message.reply_text("❌ حدث خطأ أثناء تحديث المسؤول.")

async def error_handler(update, context):
    """Handle errors in telegram-bot-api."""
    logger.error(f"Update {update} caused error {context.error}")
    
    if update and update.effective_chat:
        await update.effective_chat.send_message(
            "⚠️ حدث خطأ أثناء معالجة طلبك. الرجاء المحاولة مرة أخرى لاحقًا."
        )

def cleanup_downloads():
    """Clean up downloads directory."""
    try:
        if os.path.exists(DOWNLOAD_DIR):
            for file in os.listdir(DOWNLOAD_DIR):
                file_path = os.path.join(DOWNLOAD_DIR, file)
                try:
                    if os.path.isfile(file_path):
                        os.unlink(file_path)
                    elif os.path.isdir(file_path):
                        shutil.rmtree(file_path)
                except Exception as e:
                    logger.error(f"Error deleting {file_path}: {e}")
    except Exception as e:
        logger.error(f"Error cleaning downloads: {e}")

def main():
    """Initialize and start the bot."""
    # Get a clean start by killing anything related first
    try:
        import os
        import signal
        import subprocess
        import glob
        
        # Remove any lock files that might exist from previous runs
        for lock_file in glob.glob("*.lock"):
            try:
                os.remove(lock_file)
                logger.info(f"Removed stale lock file: {lock_file}")
            except Exception as e:
                logger.warning(f"Failed to remove lock file {lock_file}: {e}")
        
        # Use pkill to terminate any existing Python processes running this script
        try:
            subprocess.run(["pkill", "-9", "-f", "python.*downloads1.py"], 
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            logger.info("Terminated any existing bot processes")
            time.sleep(2)  # Give processes time to terminate
        except Exception as e:
            logger.warning(f"pkill command failed: {e}")
    except Exception as e:
        logger.warning(f"Error during cleanup: {e}")
    
    # Initialize database
    init_database()
    
    # Clean up any old downloads
    cleanup_downloads()
    
    # Ensure the download directory exists
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    
    # Create lock file with timeout verification
    lock_file = "bot_instance.lock"
    pid = os.getpid()
    lock_data = f"{pid}:{int(time.time())}"
    
    try:
        # Only proceed if we can create the lock file
        if os.path.exists(lock_file):
            # Check if the lock is stale (older than 1 minute)
            with open(lock_file, 'r') as f:
                old_data = f.read().strip()
                try:
                    old_pid, timestamp = old_data.split(":")
                    if int(time.time()) - int(timestamp) < 60:
                        logger.error(f"Another bot instance is already running (PID: {old_pid})")
                        return
                except:
                    pass  # Invalid lock file format, we'll overwrite it
            
        # Write our PID to the lock file
        with open(lock_file, 'w') as f:
            f.write(lock_data)
        logger.info(f"Created lock file for PID {pid}")
    except Exception as e:
        logger.error(f"Error managing lock file: {e}")
        # We'll continue anyway
    
    try:
        # Log basic information for troubleshooting
        logger.info(f"Bot token (masked): {TOKEN[:5]}...{TOKEN[-5:]}")
        logger.info(f"Python version: {sys.version}")
        logger.info(f"Current working directory: {os.getcwd()}")
        
        # Create the Application
        application = Application.builder().token(TOKEN).build()
    
        # Register handlers
        application.add_handler(CommandHandler("start", start_handler))
        application.add_handler(CommandHandler("help", help_handler))
        application.add_handler(CommandHandler("formats", formats_handler))
        application.add_handler(CommandHandler("admin", admin_handler))
        application.add_handler(CommandHandler("stats", stats_handler))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
        application.add_handler(CallbackQueryHandler(callback_handler))
        
        # Register error handler
        application.add_error_handler(error_handler)
        
        # Start the Bot - drop pending updates to avoid backlog
        logger.info("Starting bot polling...")
        application.run_polling(
            drop_pending_updates=True,
            connect_timeout=30,
            read_timeout=30,
            write_timeout=30,
            pool_timeout=30
        )
    except Exception as e:
        logger.error(f"Fatal error in main bot process: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
    finally:
        # Clean up lock file when the bot exits
        try:
            if os.path.exists(lock_file):
                os.remove(lock_file)
                logger.info("Removed lock file on exit")
        except Exception as e:
            logger.warning(f"Failed to remove lock file: {e}")

if __name__ == "__main__":
    main()