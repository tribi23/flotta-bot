# ==============================================================================
# FLOTTA BOT - VERSIONE SICURA (NO CREDENZIALI ESPOSTE)
# Funzionalità:
# - Inserimento guidato dati veicoli
# - Generazione report mensili
# - Controllo accessi per utenti autorizzati
# ==============================================================================

import logging
from datetime import datetime
import os
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
    CallbackQueryHandler,
)
import pandas as pd

# Configurazione logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Costanti (da impostare come variabili d'ambiente)
SCOPES = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
AUTHORIZED_USERS = [362485425, 5967775955]  # ID Telegram degli utenti autorizzati

# Stati per le ConversationHandler
SELECTING_YEAR, SELECTING_MONTH = range(2)
SELECT_TARGA, GET_DRIVER, GET_KM, GET_SEGNALAZIONI = range(2, 6)

# ==============================================================================
# Funzioni Ausiliarie
# ==============================================================================

def get_google_creds():
    """Carica le credenziali Google da variabile d'ambiente"""
    creds_json = os.getenv("GOOGLE_CREDS_JSON")
    if not creds_json:
        raise ValueError("Credenziali Google non trovate nelle variabili d'ambiente")
    return ServiceAccountCredentials.from_json_keyfile_dict(json.loads(creds_json), SCOPES)

async def generate_report(context: ContextTypes.DEFAULT_TYPE, mese: int, anno: int):
    """Genera report mensile con normalizzazione dati"""
    try:
        sheet = context.bot_data["spreadsheet"].sheet1
        records = sheet.get_all_records()
        
        if not records:
            return "", "ℹ️ Nessun dato trovato"

        df = pd.DataFrame(records)
        required_cols = ['DATA', 'DRIVER', 'TARGA']
        if not all(col in df.columns for col in required_cols):
            return "", "❌ Intestazioni mancanti"

        # Normalizzazione dati
        df['DATA'] = pd.to_datetime(df['DATA'], errors='coerce')
        df['DRIVER'] = df['DRIVER'].astype(str).str.strip().str.upper()
        df['TARGA'] = df['TARGA'].astype(str).str.replace(' ', '').str.upper()
        df = df.dropna(subset=['DATA', 'DRIVER', 'TARGA'])

        # Filtra per mese/anno
        df_mese = df[(df['DATA'].dt.month == mese) & (df['DATA'].dt.year == anno)]
        if df_mese.empty:
            return "", f"ℹ️ Nessun dato per {mese:02d}/{anno}"

        # Elaborazione report
        report = (
            df_mese.groupby(['DRIVER', 'TARGA'])
            .agg(GIORNI=('DATA', 'size'), ELENCO_GIORNI=('DATA', lambda x: ', '.join(map(str, x.dt.day.unique()))))
            .reset_index()
            .sort_values(['DRIVER', 'GIORNI'], ascending=[True, False])
        )

        # Formattazione output
        nome_mese = datetime(anno, mese, 1).strftime('%B')
        report_msg = f"📊 Report {nome_mese} {anno}\n\n"
        
        for _, row in report.iterrows():
            report_msg += f"👤 {row['DRIVER']}\n🚗 {row['TARGA']}: {row['GIORNI']} giorni ({row['ELENCO_GIORNI']})\n\n"

        return report_msg, "✅ Report generato"
    except Exception as e:
        logger.error(f"Errore generazione report: {e}")
        return "", f"❌ Errore: {str(e)}"

# ==============================================================================
# Gestori Comandi
# ==============================================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gestore comando /start"""
    await update.message.reply_text(
        "🛠️ Bot Flotta Veicoli\n"
        "Comandi disponibili:\n"
        "/nuovo - Inserisci nuovi dati\n"
        "/report - Genera report mensile"
    )

async def nuovo_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Avvia inserimento nuovo dato"""
    if update.effective_user.id not in AUTHORIZED_USERS:
        await update.message.reply_text("⛔ Accesso negato")
        return ConversationHandler.END
    
    try:
        sheet = context.bot_data["spreadsheet"].sheet1
        df = pd.DataFrame(sheet.get_all_records())
        targhe = df['TARGA'].dropna().unique()
        
        keyboard = [
            [InlineKeyboardButton(targa, callback_data=targa)]
            for targa in sorted(targhe)
        ]
        keyboard.append([InlineKeyboardButton("❌ Annulla", callback_data="cancel")])
        
        await update.message.reply_text(
            "🚗 Seleziona targa:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return SELECT_TARGA
    except Exception as e:
        logger.error(f"Errore nuovo_start: {e}")
        await update.message.reply_text("❌ Errore di sistema")
        return ConversationHandler.END

# ... (altri gestori comandi mantenendo la stessa logica ma con miglior gestione errori)

# ==============================================================================
# Inizializzazione Bot
# ==============================================================================

def main():
    try:
        # Configurazione Google Sheets
        creds, spreadsheet = get_google_creds()
        gc = gspread.authorize(creds)
        spreadsheet = gc.open_by_key(os.getenv("SPREADSHEET_ID"))
        
        # Inizializzazione bot
        app = Application.builder() \
            .token(os.getenv("TELEGRAM_BOT_TOKEN")) \
            .build()
            
        app.bot_data["spreadsheet"] = spreadsheet

        # Configurazione handler
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler("nuovo", nuovo_start)],
            states={
                SELECT_TARGA: [CallbackQueryHandler(targa_handler)],
                # ... altri stati
            },
            fallbacks=[CommandHandler("cancel", cancel)]
        )
        
        app.add_handler(CommandHandler("start", start))
        app.add_handler(conv_handler)
        
        logger.info("Bot avviato correttamente")
        app.run_polling()
        
    except Exception as e:
        logger.critical(f"Errore inizializzazione: {e}")
        exit(1)

if __name__ == "__main__":
    main()
