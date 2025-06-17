import streamlit as st
from google.oauth2 import service_account
from googleapiclient.discovery import build
from anthropic import Anthropic
from PIL import Image
import io
import zipfile
import logging
import base64

# --- Logger Setup ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- API Key Validation ---
def validate_keys():
    if 'claude_key' not in st.secrets or not st.secrets['claude_key'].startswith('sk-ant'):
        st.error("Claude API Key fehlt oder ist ungültig")
        st.stop()

validate_keys()

# --- UI-Einstellungen ---
st.set_page_config(layout="centered", page_title="Koifox-Bot", page_icon="🦊")
st.title("🦊 Koifox-Bot")
st.markdown("""  
    *Made with coffee, deep minimal and tiny gummy bears*  
""")

# --- Google Drive-Verbindung ---
@st.cache_resource
def load_knowledge_from_drive():
    knowledge_base = ""
    if "gdrive_creds" not in st.secrets:
        return knowledge_base
        
    try:
        creds = service_account.Credentials.from_service_account_info(st.secrets["gdrive_creds"])
        drive_service = build("drive", "v3", credentials=creds)
        
        folder_response = drive_service.files().list(
            q="name='IRW_Bot_Gehirn' and mimeType='application/vnd.google-apps.folder'",
            pageSize=1,
            fields="files(id)"
        ).execute()
        
        folder = folder_response.get('files', [{}])[0]
        if not folder.get('id'):
            return knowledge_base
            
        zip_response = drive_service.files().list(
            q=f"'{folder['id']}' in parents and mimeType='application/zip'",
            pageSize=1,
            fields="files(id)"
        ).execute()
        
        zip_file = zip_response.get('files', [{}])[0]
        if not zip_file.get('id'):
            return knowledge_base
            
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

# --- Vollständiger Accounting Prompt (IMMER verwenden) ---
ACCOUNTING_PROMPT = """
You are a highly qualified accounting expert with PhD-level knowledge of the university course "Internes Rechnungswesen (31031)" at Fernuniversität Hagen. 
Your task is to answer exam questions regarding this course with 100% accuracy using the provided image.

THEORETICAL SCOPE
Use only the decision-oriented German managerial-accounting (Controlling) framework:
• Cost-type, cost-center and cost-unit accounting (Kostenarten-, Kostenstellen-, Kostenträgerrechnung)
• Full, variable, marginal, standard (Plankosten-) and process/ABC costing systems
• Flexible and Grenzplankostenrechnung variance analysis
• Single- and multi-level contribution-margin accounting and break-even logic
• Causality & allocation (Verursachungs- und Zurechnungsprinzip)
• Business-economics MRS convention (MRS = MP₂ / MP₁ unless stated otherwise)
• Activity-analysis production & logistics models (LP, Standort- & Transportprobleme)
• Marketing segmentation, price-elasticity, contribution-based pricing & mix planning

INSTRUCTIONS:
1. Analyze the image carefully to identify all exam tasks
2. For each task, provide:
   - Aufgabe [Nr]: [Präzise Lösung]
   - Begründung: [1-Satz-Erklärung auf Deutsch mit Fachbegriffen]
3. Use the knowledge base below when relevant
4. Be extremely precise with calculations
5. Format answers clearly and consistently
"""

# --- Hauptfunktion ---
def process_exam_image(image, use_knowledge_base=False):
    """Verarbeitet Klausurbild mit Claude 4 Opus Vision"""
    try:
        buffered = io.BytesIO()
        
        # Bildoptimierung (Balance zwischen Qualität und Größe)
        max_dimension = 1536
        image.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)
        
        if image.mode in ('RGBA', 'P'):
            rgb_image = Image.new('RGB', image.size, (255, 255, 255))
            rgb_image.paste(image, mask=image.split()[-1] if image.mode == 'RGBA' else None)
            image = rgb_image
        
        image.save(buffered, format="JPEG", quality=90)
        image_data = base64.b64encode(buffered.getvalue()).decode()
        
        # Knowledge Base Section
        knowledge_section = ""
        if use_knowledge_base:
            knowledge_base = load_knowledge_from_drive()
            if knowledge_base:
                # Nur relevanten Teil nehmen (erste 8000 Zeichen)
                knowledge_section = f"\n\nKNOWLEDGE BASE (relevant excerpts):\n{knowledge_base[:8000]}"
        
        prompt = ACCOUNTING_PROMPT.format(knowledge_section=knowledge_section)
        
        # API-Aufruf
        client = Anthropic(api_key=st.secrets["claude_key"])
        response = client.messages.create(
            model="claude-4-opus-20250514",
            max_tokens=1200,  # Etwas mehr für komplexe Aufgaben
            temperature=0,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": image_data
                        }
                    },
                    {
                        "type": "text",
                        "text": prompt
                    }
                ]
            }]
        )
        
        return response.content[0].text
        
    except Exception as e:
        logger.error(f"Verarbeitungsfehler: {str(e)}")
        raise e

# --- UI ---
# Checkbox für Knowledge Base
col1, col2 = st.columns([3, 1])
with col1:
    use_knowledge = st.checkbox(
        "Kursmaterial einbeziehen", 
        value=False,
        help="Aktivieren für komplexe Theoriefragen."
    )
with col2:
    if use_knowledge:
        st.warning("Höhere Kosten")

# Datei-Upload
uploaded_file = st.file_uploader(
    "**Klausuraufgabe hochladen...**",
    type=["png", "jpg", "jpeg"],
    help="Lade ein Bild der Klausuraufgabe hoch"
)

if uploaded_file is not None:
    try:
        # Bild laden und anzeigen
        image = Image.open(uploaded_file)
        st.image(image, caption="Hochgeladene Klausuraufgabe", use_container_width=True)
        
        # Aufgabe analysieren
        with st.spinner("Analysiere Aufgabe..."):
            result = process_exam_image(image, use_knowledge)
        
        # Ergebnisse anzeigen
        st.markdown("---")
        st.markdown("### Lösungen:")
        
        # Formatierte Ausgabe
        lines = result.split('\n')
        for line in lines:
            if line.strip():
                if line.startswith('Aufgabe'):
                    # Aufgabe und Lösung hervorheben
                    parts = line.split(':', 1)
                    if len(parts) == 2:
                        st.markdown(f"### {parts[0]}: **{parts[1].strip()}**")
                    else:
                        st.markdown(f"### {line}")
                elif line.startswith('Begründung:'):
                    st.markdown(f"_{line}_")
                else:
                    st.markdown(line)
                    
    except Exception as e:
        st.error(f"❌ Fehler: {str(e)}")
        st.info("Stelle sicher, dass das Bild klar lesbar ist.")

# --- Footer ---
st.markdown("---")
st.caption("Made by Fox & Powered by Claude 4 Opus Vision")
