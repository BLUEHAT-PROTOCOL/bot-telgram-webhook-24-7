from flask import Flask, request, jsonify
import telegram
import os
import requests
import threading
import time
import logging
import zipfile
import uuid
import json
import base64
import re
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, CallbackContext

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Konfigurasi Hosting
# Netlify
NETLIFY_ACCESS_TOKEN = "nfp_ftGqiPvV7B6vdwFAgtfmLsX8ssscvuCv8fb9"
NETLIFY_API_URL = "https://api.netlify.com/api/v1"

# Vercel
VERCEL_ACCESS_TOKEN = "iIggLvXFuEAZEK1gmzUrqrNr"
VERCEL_API_URL = "https://api.vercel.com"

# GitHub
GITHUB_TOKEN = "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"
GITHUB_API_URL = "https://api.github.com"

# Konfigurasi Bot
BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
ADMIN_ID = 6807064800  # ID Telegram admin
QRIS_LINK = "https://ibb.co.com/C3nqRm9V"  # Link QRIS Anda

# Direktori sementara untuk file
TEMP_DIR = "/tmp/temp_files"
os.makedirs(TEMP_DIR, exist_ok=True)

# Penyimpanan data sementara
user_data = {}
websites = {}

# States untuk conversation handler
SET_PROJECT_NAME, SET_CUSTOM_DOMAIN, CHOOSE_HOSTING = range(3)

# Inisialisasi Flask app
app = Flask(__name__)

# Fungsi untuk membuat progress bar
def create_progress_bar(percentage):
    """Membuat progress bar visual berdasarkan persentase"""
    filled_length = int(20 * percentage // 100)
    bar = '█' * filled_length + '-' * (20 - filled_length)
    return f"|{bar}| {percentage}%"

# Fungsi untuk deploy ke Netlify
async def deploy_to_netlify(context, file_path, site_name, custom_domain, chat_id):
    """Deploy file ke Netlify"""
    headers = {
        "Authorization": f"Bearer {NETLIFY_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    
    # Buat site baru
    site_data = {
        "name": site_name
    }
    
    if custom_domain:
        site_data["custom_domain"] = custom_domain
    
    try:
        create_response = requests.post(
            f"{NETLIFY_API_URL}/sites",
            headers=headers,
            json=site_data,
            timeout=30
        )
        
        if create_response.status_code not in (200, 201):
            logger.error(f"Error creating Netlify site: {create_response.status_code} - {create_response.text}")
            return None
        
        site_info = create_response.json()
        site_id = site_info.get('id')
        logger.info(f"Netlify site created with ID: {site_id}")
        
        # Deploy file
        if file_path.endswith('.html'):
            # Baca file HTML
            with open(file_path, 'rb') as f:
                file_content = f.read()
            
            # Decode content
            try:
                html_content = file_content.decode('utf-8')
            except UnicodeDecodeError:
                try:
                    html_content = file_content.decode('latin-1')
                except Exception as e:
                    logger.error(f"Failed to decode HTML file: {e}")
                    return None
            
            # Siapkan payload untuk deploy
            deploy_payload = {
                "files": {
                    "index.html": {
                        "content": html_content
                    }
                }
            }
            
            # Kirim ke Netlify
            deploy_response = requests.post(
                f"{NETLIFY_API_URL}/sites/{site_id}/deploys",
                headers=headers,
                json=deploy_payload,
                timeout=60
            )
            
            if deploy_response.status_code in (200, 201, 202):
                deploy_info = deploy_response.json()
                deploy_id = deploy_info.get('id')
                
                if deploy_id:
                    # Tunggu deployment selesai
                    success = await create_netlify_site_with_progress(context, site_id, deploy_id, chat_id, max_wait=300)
                    
                    if success:
                        # Dapatkan data site terbaru
                        site_response = requests.get(
                            f"{NETLIFY_API_URL}/sites/{site_id}",
                            headers=headers,
                            timeout=30
                        )
                        
                        if site_response.status_code == 200:
                            final_site_info = site_response.json()
                            website_url = final_site_info.get('ssl_url') or final_site_info.get('url')
                            
                            return {
                                'url': website_url,
                                'admin_url': final_site_info.get('admin_url', ''),
                                'id': final_site_info.get('id', ''),
                                'name': final_site_info.get('name', site_name),
                                'ssl_url': final_site_info.get('ssl_url', ''),
                                'custom_domain': final_site_info.get('custom_domain', custom_domain or ''),
                                'platform': 'Netlify'
                            }
        else:
            # Deploy ZIP
            with open(file_path, 'rb') as f:
                files = {
                    'file': (os.path.basename(file_path), f, 'application/zip')
                }
                
                deploy_headers = {
                    "Authorization": f"Bearer {NETLIFY_ACCESS_TOKEN}"
                }
                
                deploy_response = requests.post(
                    f"{NETLIFY_API_URL}/sites/{site_id}/deploys",
                    headers=deploy_headers,
                    files=files,
                    timeout=120
                )
                
                if deploy_response.status_code in (200, 201, 202):
                    deploy_info = deploy_response.json()
                    deploy_id = deploy_info.get('id')
                    
                    if deploy_id:
                        # Tunggu deployment selesai
                        success = await create_netlify_site_with_progress(context, site_id, deploy_id, chat_id, max_wait=300)
                        
                        if success:
                            # Dapatkan data site terbaru
                            site_response = requests.get(
                                f"{NETLIFY_API_URL}/sites/{site_id}",
                                headers=headers,
                                timeout=30
                            )
                            
                            if site_response.status_code == 200:
                                final_site_info = site_response.json()
                                website_url = final_site_info.get('ssl_url') or final_site_info.get('url')
                                
                                return {
                                    'url': website_url,
                                    'admin_url': final_site_info.get('admin_url', ''),
                                    'id': final_site_info.get('id', ''),
                                    'name': final_site_info.get('name', site_name),
                                    'ssl_url': final_site_info.get('ssl_url', ''),
                                    'custom_domain': final_site_info.get('custom_domain', custom_domain or ''),
                                    'platform': 'Netlify'
                                }
        
        return None
    except Exception as e:
        logger.error(f"Exception in deploy_to_netlify: {e}")
        return None

# Fungsi untuk deploy ke Vercel
async def deploy_to_vercel(context, file_path, site_name, custom_domain, chat_id):
    """Deploy file ke Vercel"""
    if not VERCEL_ACCESS_TOKEN:
        logger.error("Vercel access token not provided")
        return None
    
    headers = {
        "Authorization": f"Bearer {VERCEL_ACCESS_TOKEN}"
    }
    
    try:
        # Buat project baru
        project_data = {
            "name": site_name
        }
        
        project_response = requests.post(
            f"{VERCEL_API_URL}/v1/projects",
            headers=headers,
            json=project_data,
            timeout=30
        )
        
        if project_response.status_code not in (200, 201):
            logger.error(f"Error creating Vercel project: {project_response.status_code} - {project_response.text}")
            return None
        
        project_info = project_response.json()
        project_id = project_info.get('id')
        logger.info(f"Vercel project created with ID: {project_id}")
        
        # Siapkan file untuk deployment
        files_data = []
        
        if file_path.endswith('.html'):
            # Baca file HTML
            with open(file_path, 'rb') as f:
                file_content = f.read()
            
            # Encode content ke base64
            encoded_content = base64.b64encode(file_content).decode('utf-8')
            
            # Siapkan payload untuk deployment
            files_data.append({
                "file": "index.html",
                "data": encoded_content,
                "encoding": "base64"
            })
        else:
            # Untuk ZIP, ekstrak dulu
            logger.info(f"Processing ZIP file: {file_path}")
            with zipfile.ZipFile(file_path, 'r') as zip_ref:
                file_list = zip_ref.namelist()
                logger.info(f"Files in ZIP: {file_list}")
                
                for file_name in file_list:
                    if not file_name.startswith('__MACOSX/') and not file_name.startswith('.'):
                        try:
                            with zip_ref.open(file_name) as file:
                                content = file.read()
                                encoded_content = base64.b64encode(content).decode('utf-8')
                                
                                files_data.append({
                                    "file": file_name,
                                    "data": encoded_content,
                                    "encoding": "base64"
                                })
                                logger.info(f"Added file to deploy: {file_name}")
                        except Exception as e:
                            logger.error(f"Error extracting {file_name}: {e}")
        
        # Siapkan payload untuk deployment
        deploy_data = {
            "name": site_name,
            "files": files_data,
            "target": "production"
        }
        
        logger.info(f"Deploying ZIP to Vercel project {project_id}")
        logger.info(f"Number of files: {len(files_data)}")
        
        # Deploy ke Vercel
        deploy_response = requests.post(
            f"{VERCEL_API_URL}/v13/deployments",
            headers=headers,
            json=deploy_data,
            timeout=120
        )
        
        logger.info(f"Deploy response status: {deploy_response.status_code}")
        logger.info(f"Deploy response: {deploy_response.text}")
        
        if deploy_response.status_code in (200, 201, 202):
            deploy_info = deploy_response.json()
            deploy_id = deploy_info.get('id')
            
            if deploy_id:
                logger.info(f"Deploy started with ID: {deploy_id}")
                
                # Tunggu deployment selesai
                success = await create_vercel_site_with_progress(context, project_id, deploy_id, chat_id, max_wait=300)
                
                if success:
                    # Dapatkan data project terbaru
                    project_response = requests.get(
                        f"{VERCEL_API_URL}/v1/projects/{project_id}",
                        headers=headers,
                        timeout=30
                    )
                    
                    if project_response.status_code == 200:
                        final_project_info = project_response.json()
                        
                        # Dapatkan URL
                        urls = final_project_info.get('targets', {}).get('production', {}).get('alias', [])
                        if urls:
                            website_url = f"https://{urls[0]}"
                        else:
                            website_url = f"https://{project_id}.vercel.app"
                        
                        logger.info(f"Vercel deployment successful. URL: {website_url}")
                        
                        return {
                            'url': website_url,
                            'admin_url': f"https://vercel.com/{final_project_info.get('name', site_name)}",
                            'id': project_id,
                            'name': final_project_info.get('name', site_name),
                            'ssl_url': website_url,
                            'custom_domain': custom_domain or '',
                            'platform': 'Vercel'
                        }
        else:
            logger.error(f"Vercel deploy failed with status: {deploy_response.status_code}")
            logger.error(f"Vercel deploy response: {deploy_response.text}")
        
        return None
    except Exception as e:
        logger.error(f"Exception in deploy_to_vercel: {e}")
        return None

# Fungsi untuk deploy ke GitHub Pages
async def deploy_to_github_pages(context, file_path, repo_name, custom_domain, chat_id):
    """Deploy file ke GitHub Pages"""
    if not GITHUB_TOKEN:
        logger.error("GitHub token not provided")
        return None
    
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    
    try:
        # Buat repository baru
        repo_data = {
            "name": repo_name,
            "auto_init": True
        }
        
        repo_response = requests.post(
            f"{GITHUB_API_URL}/user/repos",
            headers=headers,
            json=repo_data,
            timeout=30
        )
        
        if repo_response.status_code not in (200, 201):
            logger.error(f"Error creating GitHub repo: {repo_response.status_code} - {repo_response.text}")
            return None
        
        repo_info = repo_response.json()
        repo_owner = repo_info.get('owner', {}).get('login')
        repo_name = repo_info.get('name')
        repo_full_name = repo_info.get('full_name')
        default_branch = repo_info.get('default_branch', 'main')
        
        logger.info(f"GitHub repo created: {repo_full_name}")
        
        # Siapkan file untuk deployment
        if file_path.endswith('.html'):
            # Baca file HTML
            with open(file_path, 'rb') as f:
                file_content = f.read()
            
            # Encode content ke base64
            encoded_content = base64.b64encode(file_content).decode('utf-8')
            
            # Buat file di repository
            file_data = {
                "message": "Add index.html",
                "content": encoded_content,
                "branch": default_branch,
                "encoding": "base64"
            }
            
            file_response = requests.put(
                f"{GITHUB_API_URL}/repos/{repo_full_name}/contents/index.html",
                headers=headers,
                json=file_data,
                timeout=30
            )
            
            if file_response.status_code not in (200, 201):
                logger.error(f"Error creating file: {file_response.status_code} - {file_response.text}")
                return None
        else:
            # Untuk ZIP, ekstrak dulu
            with zipfile.ZipFile(file_path, 'r') as zip_ref:
                file_list = zip_ref.namelist()
                
                for file_name in file_list:
                    if not file_name.startswith('__MACOSX/') and not file_name.startswith('.'):
                        try:
                            with zip_ref.open(file_name) as file:
                                content = file.read()
                                
                                # Encode content ke base64
                                encoded_content = base64.b64encode(content).decode('utf-8')
                                
                                file_data = {
                                    "message": f"Add {file_name}",
                                    "content": encoded_content,
                                    "branch": default_branch,
                                    "encoding": "base64"
                                }
                                
                                # Pastikan path file benar
                                file_path_github = file_name
                                
                                # Buat file di repository
                                file_response = requests.put(
                                    f"{GITHUB_API_URL}/repos/{repo_full_name}/contents/{file_path_github}",
                                    headers=headers,
                                    json=file_data,
                                    timeout=30
                                )
                                
                                if file_response.status_code not in (200, 201):
                                    logger.error(f"Error creating file {file_name}: {file_response.status_code} - {file_response.text}")
                        except Exception as e:
                            logger.error(f"Error extracting {file_name}: {e}")
        
        # Aktifkan GitHub Pages
        pages_data = {
            "source": {
                "branch": default_branch,
                "path": "/"
            }
        }
        
        pages_response = requests.post(
            f"{GITHUB_API_URL}/repos/{repo_full_name}/pages",
            headers=headers,
            json=pages_data,
            timeout=30
        )
        
        if pages_response.status_code not in (200, 201, 202):
            logger.error(f"Error enabling GitHub Pages: {pages_response.status_code} - {pages_response.text}")
            return None
        
        # Tunggu GitHub Pages siap
        success = await create_github_pages_with_progress(context, repo_full_name, chat_id, max_wait=300)
        
        if success:
            # Dapatkan data GitHub Pages
            pages_response = requests.get(
                f"{GITHUB_API_URL}/repos/{repo_full_name}/pages",
                headers=headers,
                timeout=30
            )
            
            if pages_response.status_code == 200:
                pages_info = pages_response.json()
                website_url = pages_info.get('html_url')
                
                # Tambahkan custom domain jika ada
                if custom_domain:
                    domain_data = {
                        "name": custom_domain
                    }
                    
                    domain_response = requests.post(
                        f"{GITHUB_API_URL}/repos/{repo_full_name}/pages/domains",
                        headers=headers,
                        json=domain_data,
                        timeout=30
                    )
                    
                    if domain_response.status_code in (200, 201, 202):
                        logger.info(f"Custom domain {custom_domain} added to GitHub Pages")
                
                return {
                    'url': website_url,
                    'admin_url': f"https://github.com/{repo_full_name}/settings/pages",
                    'id': repo_full_name,
                    'name': repo_name,
                    'ssl_url': website_url,
                    'custom_domain': custom_domain or '',
                    'platform': 'GitHub Pages'
                }
        
        return None
    except Exception as e:
        logger.error(f"Exception in deploy_to_github_pages: {e}")
        return None

# Fungsi untuk membuat progress bar (simplified for Render)
async def create_progress_bar_async(context, chat_id, platform, percentage, status_text):
    """Membuat progress bar visual"""
    progress_text = (
        f"🚀 Memproses pembuatan website di {platform}...\n\n"
        f"{create_progress_bar(percentage)}\n"
        f"{status_text}"
    )
    
    await context.bot.send_message(chat_id, progress_text)

# Fungsi untuk handle file (simplified)
async def handle_file(update: Update, context: CallbackContext) -> None:
    user_id = update.effective_user.id
    document = update.message.document
    
    if not document.file_name.endswith(('.zip', '.html')):
        await update.message.reply_text("Hanya file ZIP atau HTML yang diterima.")
        return
    
    # Simpan info file
    user_data[user_id] = {
        'file_id': document.file_id,
        'file_name': document.file_name,
        'state': 'AWAITING_PAYMENT',
        'username': update.effective_user.username
    }
    
    # Kirim instruksi pembayaran
    keyboard = [
        [InlineKeyboardButton("Bayar Sekarang", url=QRIS_LINK)],
        [InlineKeyboardButton("Sudah Bayar", callback_data=f"paymentproof_{user_id}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"📁 File {document.file_name} diterima!\n\n"
        f"💳 Silakan lakukan pembayaran melalui link QRIS:\n"
        f"{QRIS_LINK}\n\n"
        f"✅ Setelah membayar, klik tombol 'Sudah Bayar' dan kirim bukti pembayaran.",
        reply_markup=reply_markup
    )
    
    # Notifikasi admin
    await context.bot.send_message(
        ADMIN_ID,
        f"🔔 Permintaan website baru dari @{update.effective_user.username} (ID: {user_id})\n"
        f"📄 File: {document.file_name}\n\n"
        f"⏳ Menunggu pembayaran..."
    )

# Fungsi start
async def start(update: Update, context: CallbackContext) -> None:
    """Send a message when the command /start is issued."""
    user = update.effective_user
    
    if user.id == ADMIN_ID:
        await update.message.reply_text(
            "🤖 Bot Website Deployer siap!\n\n"
            "Anda adalah admin. Bot akan menunggu pengguna mengirim file website.\n\n"
            "📋 Fitur:\n"
            "• Deploy ke Netlify\n"
            "• Deploy ke Vercel\n"
            "• Deploy ke GitHub Pages\n"
            "• Support file HTML dan ZIP\n"
            "• Custom domain\n"
            "• Progress bar"
        )
    else:
        await update.message.reply_text(
            "🤖 Selamat datang di Bot Website Deployer!\n\n"
            "Silakan kirim file website (HTML atau ZIP) untuk mulai deploy.\n\n"
            "📋 Cara penggunaan:\n"
            "1. Kirim file website (HTML atau ZIP)\n"
            "2. Lakukan pembayaran\n"
            "3. Tunggu persetujuan admin\n"
            "4. Pilih platform hosting\n"
            "5. Selesai!"
        )

# Route untuk Flask app
@app.route('/')
def home():
    return "Bot is running!"

@app.route('/health')
def health():
    return jsonify({"status": "ok", "timestamp": time.time()})

# Route untuk webhook Telegram
@app.route('/webhook', methods=['POST'])
def webhook():
    """Handle webhook updates from Telegram"""
    if request.method == "POST":
        update = telegram.Update.de_json(request.get_json(force=True), application.bot)
        application.process_update(update)
        return jsonify({"status": "ok"})
    return jsonify({"status": "error", "message": "Method not allowed"})

# Keep-alive function
def keep_alive():
    """Keep the app awake by making requests to itself"""
    while True:
        try:
            # Get the service URL from environment or use default
            service_url = os.environ.get('RENDER_EXTERNAL_URL', 'http://localhost:10000')
            requests.get(f"{service_url}/health", timeout=10)
            logger.info("Keep-alive request sent")
        except Exception as e:
            logger.error(f"Keep-alive error: {e}")
        
        # Sleep for 5 minutes
        time.sleep(300)

# Inisialisasi aplikasi Telegram
application = Application.builder().token(BOT_TOKEN).build()

# Tambahkan handler
application.add_handler(CommandHandler("start", start))
application.add_handler(MessageHandler(filters.Document.ALL, handle_file))

if __name__ == "__main__":
    # Start keep-alive thread
    keep_alive_thread = threading.Thread(target=keep_alive)
    keep_alive_thread.daemon = True
    keep_alive_thread.start()
    
    # Set webhook
    webhook_url = f"{os.environ.get('RENDER_EXTERNAL_URL')}/webhook"
    application.bot.set_webhook(url=webhook_url)
    logger.info(f"Webhook set to: {webhook_url}")
    
    # Run Flask app
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
