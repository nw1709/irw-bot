import streamlit as st
from google.oauth2 import service_account
from googleapiclient.discovery import build
from anthropic import Anthropic
from PIL import Image
import google.generativeai as genai
import io
import zipfile
import logging

# --- Logger Setup ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Session State Reset ---
if 'last_upload' not in st.session_state:
    st.session_state.last_upload = None

# --- API Key Validation ---
def validate_keys():
    required_keys = {
        'gemini_key': ('AIza', "Gemini"),
        'claude_key': ('sk-ant', "Claude")
    }
    missing = []
    invalid = []
    
    for key, (prefix, name) in required_keys.items():
        if key not in st.secrets:
            missing.append(name)
        elif not st.secrets[key].startswith(prefix):
            invalid.append(name)
    
    if missing or invalid:
        st.error(f"API Key Problem: Missing {', '.join(missing)} | Invalid {', '.join(invalid)}")
        st.stop()

validate_keys()

# --- UI-Einstellungen ---
st.set_page_config(layout="centered", page_title="Koifox-Bot", page_icon="🦊")
st.title("🦊 Koifox-Bot")
st.markdown("*Using Gemini for OCR + Claude 4 Opus for solutions*")

# --- Google Drive-Verbindung ---
@st.cache_resource
def load_knowledge_from_drive():
    knowledge_base = ""
    if "gdrive_creds" not in st.secrets:
        return knowledge_base
        
    try:
        creds = service_account.Credentials.from_service_account_info(st.secrets["gdrive_creds"])
        drive_service = build("drive", "v3", credentials=creds)
        
        # Ordner finden
        folder_response = drive_service.files().list(
            q="name='IRW_Bot_Gehirn' and mimeType='application/vnd.google-apps.folder'",
            pageSize=1,
            fields="files(id)"
        ).execute()
        
        folder = folder_response.get('files', [{}])[0]
        if not folder.get('id'):
            return knowledge_base
            
        # ZIP-Datei finden
        zip_response = drive_service.files().list(
            q=f"'{folder['id']}' in parents and mimeType='application/zip'",
            pageSize=1,
            fields="files(id)"
        ).execute()
        
        zip_file = zip_response.get('files', [{}])[0]
        if not zip_file.get('id'):
            return knowledge_base
            
        # ZIP herunterladen und entpacken
        downloaded = drive_service.files().get_media(fileId=zip_file['id']).execute()
        with zipfile.ZipFile(io.BytesIO(downloaded)) as zip_ref:
            for file_name in zip_ref.namelist():
                if file_name.endswith(('.txt', '.md')):
                    try:
                        content = zip_ref.read(file_name).decode('utf-8', errors='ignore')
                        knowledge_base += f"\n\n--- {file_name} ---\n{content}"
                    except Exception as e:
                        logger.warning(f"Konnte {file_name} nicht lesen: {e}")
                        
        logger.info(f"Knowledge Base geladen: {len(knowledge_base)} Zeichen")
        return knowledge_base
        
    except Exception as e:
        logger.error(f"Drive-Fehler: {str(e)}")
        return knowledge_base

# --- Gemini Flash Konfiguration ---
genai.configure(api_key=st.secrets["gemini_key"])
vision_model = genai.GenerativeModel("gemini-1.5-flash")

# --- OCR mit Gemini ---
def extract_text_with_gemini(image):
    """Extrahiert Text aus Bild mit Gemini Flash"""
    try:
        response = vision_model.generate_content(
            [
                "Extract ALL text from this exam image EXACTLY as written. Include all question numbers, text, and answer options (A, B, C, D, E). Do NOT interpret or solve.",
                image
            ],
            generation_config={
                "temperature": 0,
                "max_output_tokens": 4000
            }
        )
        return response.text.strip()
    except Exception as e:
        logger.error(f"Gemini OCR Error: {str(e)}")
        raise e

# --- UI Optionen ---
col1, col2 = st.columns([1, 1])
with col1:
    use_knowledge = st.checkbox(
        "📚 Kursmaterial verwenden", 
        value=False,
        help="Für komplexe Theoriefragen. Erhöht Kosten & Laufzeit."
    )
with col2:
    debug_mode = st.checkbox(
        "🔍 Debug-Modus", 
        value=False, 
        help="Zeigt OCR-Ergebnis und Prompt"
    )

# --- Datei-Upload ---
uploaded_file = st.file_uploader(
    "**Klausuraufgabe hochladen...**",
    type=["png", "jpg", "jpeg"],
    key="file_uploader"
)

if uploaded_file is not None:
    # Reset bei neuer Datei
    file_id = uploaded_file.file_id
    if st.session_state.last_upload != file_id:
        st.session_state.last_upload = file_id
        if 'ocr_result' in st.session_state:
            del st.session_state.ocr_result
    
    try:
        # Bild laden und anzeigen
        image = Image.open(uploaded_file)
        st.image(image, caption="Hochgeladene Klausuraufgabe", use_container_width=True)
        
        # OCR nur wenn noch nicht gemacht
        if 'ocr_result' not in st.session_state:
            with st.spinner("📖 Lese Text mit Gemini Flash..."):
                st.session_state.ocr_result = extract_text_with_gemini(image)
        
        ocr_text = st.session_state.ocr_result
        
        # Debug: OCR-Ergebnis anzeigen
        if debug_mode:
            st.markdown("### 🔍 OCR-Ergebnis:")
            st.code(ocr_text)
        
        # Button zum Lösen
        if st.button("🧮 Aufgaben lösen", type="primary"):
            
            # Knowledge Base laden wenn gewünscht
            knowledge_section = ""
            if use_knowledge:
                with st.spinner("📚 Lade Kursmaterial..."):
                    knowledge_base = load_knowledge_from_drive()
                    if knowledge_base:
                        # Begrenzen auf 10.000 Zeichen
                        knowledge_section = f"\n\nKURSMATERIAL (relevante Auszüge):\n{knowledge_base[:10000]}"
            
            # Flexibler Prompt
            prompt = f"""You are an expert in "Internes Rechnungswesen (31031)" at Fernuniversität Hagen.

DEIN FACHGEBIET umfasst das gesamte interne Rechnungswesen:
• Kostenarten-, Kostenstellen-, Kostenträgerrechnung
• Alle Kostenrechnungssysteme (Voll-, Teil-, Plan-, Prozesskosten etc.)
• Kalkulation und Preisfindung
• Deckungsbeitragsrechnung und Break-Even-Analyse
• Budgetierung und Abweichungsanalyse
• Investitionsrechnung
• Verrechnungspreise
• Controlling-Instrumente

ANALYSIERE diesen OCR-Text einer Klausuraufgabe:
{ocr_text}
{knowledge_section}

ANWEISUNGEN je nach Aufgabentyp:
• Multiple Choice "(x aus 5)": Prüfe jede Option einzeln, es können mehrere richtig sein
• Rechenaufgaben: Zeige Lösungsweg und Endergebnis
• Definitionen: Gib präzise Fachbegriffe wieder
• Analyseaufgaben: Strukturierte Antwort mit Begründung

FORMAT deiner Antwort:
Aufgabe [Nr]: [Lösung - je nach Aufgabentyp: Buchstabe(n), Zahl, Text]
Begründung: [Fachliche Erklärung auf Deutsch]

Verwende die Terminologie der Fernuni Hagen."""

            if debug_mode:
                st.markdown("### 🔍 Claude Prompt:")
                with st.expander("Vollständiger Prompt anzeigen"):
                    st.code(prompt)
            
            # Claude API-Aufruf
            with st.spinner("🧮 Löse Aufgaben mit Claude 4 Opus..."):
                client = Anthropic(api_key=st.secrets["claude_key"])
                response = client.messages.create(
                    model="claude-4-opus-20250514",
                    max_tokens=2000,
                    temperature=0,
                    messages=[{
                        "role": "user",
                        "content": prompt
                    }]
                )
                
                result = response.content[0].text
            
            # Ergebnisse anzeigen
            st.markdown("---")
            st.markdown("### 📊 Lösungen:")
            
            # Formatierte Ausgabe
            lines = result.split('\n')
            for line in lines:
                if line.strip():
                    if line.startswith('Aufgabe'):
                        parts = line.split(':', 1)
                        if len(parts) == 2:
                            st.markdown(f"### {parts[0]}: **{parts[1].strip()}**")
                        else:
                            st.markdown(f"### {line}")
                    elif line.startswith('Begründung:'):
                        st.markdown(f"*{line}*")
                    else:
                        st.markdown(line)
            
            # Hinweis bei aktiviertem Kursmaterial
            if use_knowledge:
                st.info("💡 Das Kursmaterial wurde für diese Antwort berücksichtigt.")
                    
    except Exception as e:
        st.error(f"❌ Fehler: {str(e)}")
        st.info("Stelle sicher, dass das Bild klar lesbar ist.")

# --- Footer ---
st.markdown("---")
st.caption("Made by Fox | Gemini OCR + Claude 4 Opus + Optional Knowledge Base")
