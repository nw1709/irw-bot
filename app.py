import streamlit as st
from google.oauth2 import service_account
from googleapiclient.discovery import build
from anthropic import Anthropic
from PIL import Image
import google.generativeai as genai
import io
import zipfile
import logging
import base64

# --- Logger Setup ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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
st.markdown("""  
    *Made with coffee, deep minimal and tiny gummy bears*  
    *Using Gemini for OCR + Claude 4 Opus for solutions*
""")

# --- Gemini Flash Konfiguration ---
genai.configure(api_key=st.secrets["gemini_key"])
vision_model = genai.GenerativeModel("gemini-1.5-flash")

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

# --- Accounting Prompt für Claude ---
ACCOUNTING_PROMPT = """
You are a highly qualified accounting expert with PhD-level knowledge of advanced university courses in accounting and finance. 
Your task is to answer questions in this domain with 100% accuracy and without any error.
 
THEORETICAL SCOPE 
Use only the decision-oriented German managerial-accounting (Controlling) framework. Include, in particular:
 
• Cost-type, cost-center and cost-unit accounting (Kostenarten-, Kostenstellen-, Kostenträgerrechnung)
• Full, variable, marginal, standard (Plankosten-) and process/ABC costing systems
• Flexible and Grenzplankostenrechnung variance analysis • Single- and multi-level contribution-margin accounting and break-even logic
• Causality & allocation (Verursachungs- und Zurechnungsprinzip) 
• Business-economics MRS convention (MRS = MP₂ / MP₁ unless stated otherwise)
• Activity-analysis production & logistics models (LP, Standort- & Transportprobleme, Supply-Chain-Planungsmatrix) 
• Marketing segmentation, price-elasticity, contribution-based pricing & mix planning 
Do not apply IFRS/GAAP valuation, classical micro-economic MRS, or any other external doctrines unless the task explicitly demands them.
 
Follow these steps to answer the question:
 
1. Read the question extremely carefully. Pay special attention to avoid any errors in visual interpretation.
 
2. Repeat the question in your reasoning by writing it down exactly as it appears in the image. Use the provided OCR text:
 
<OCR_TEXT> {{OCR_TEXT}} </OCR_TEXT>
 
3. Analyse the question step by step in your mind. Think thoroughly before answering to ensure your response is correct.
 
4. Formulate your answer. It should be short yet complete. It is crucial that your answer is CORRECT — there is no room for error.
 
5. Check your answer once more for accuracy and completeness.
 
{knowledge_section}
"""

# --- OCR mit Gemini ---
def extract_text_with_gemini(image):
    """Lese Aufgabe.."""
    try:
        response = vision_model.generate_content(
            [
                "Extract ALL text from this exam image EXACTLY as written. Include:",
                "- All question numbers and text",
                "- All answer options (A, B, C, D, E) with complete text",
                "- Special marks like '(x aus 5)' or '(5 RP)'",
                "- Mathematical formulas and numbers",
                "Do NOT interpret or solve - just extract text verbatim.",
                image
            ],
            generation_config={
                "temperature": 0,
                "max_output_tokens": 5000
            }
        )
        return response.text
    except Exception as e:
        logger.error(f"Gemini OCR Error: {str(e)}")
        raise e

# --- Lösungen mit Claude ---
def solve_with_claude(ocr_text, use_knowledge_base=False):
    """Löse Aufgabe.."""
    try:
        knowledge_section = ""
        if use_knowledge_base:
            knowledge_base = load_knowledge_from_drive()
            if knowledge_base:
                knowledge_section = f"\n\nKNOWLEDGE BASE:\n{knowledge_base[:10000]}"
        
        prompt = ACCOUNTING_PROMPT.format(
            ocr_text=ocr_text,
            knowledge_section=knowledge_section
        )
        
        client = Anthropic(api_key=st.secrets["claude_key"])
        response = client.messages.create(
            model="claude-4-opus-20250514",
            max_tokens=5000,
            temperature=0,
            system="You are an expert in German accounting. For multiple choice: analyze each option carefully.",
            messages=[{
                "role": "user",
                "content": prompt
            }]
        )
        
        return response.content[0].text
        
    except Exception as e:
        logger.error(f"Claude Error: {str(e)}")
        raise e

# --- UI ---
# Checkbox für Knowledge Base
use_knowledge = st.checkbox(
    "Kursmaterial einbeziehen", 
    value=False,
    help="Für komplexe Theoriefragen. Erhöht die Kosten."
)

# Debug-Modus
debug_mode = st.checkbox("Debug-Modus", value=False, help="Zeigt OCR-Ergebnis")

# Datei-Upload
uploaded_file = st.file_uploader(
    "**Aufgabe hochladen...**",
    type=["png", "jpg", "jpeg"],
)

if uploaded_file is not None:
    try:
        # Bild laden und anzeigen
        image = Image.open(uploaded_file)
        st.image(image, caption="Hochgeladene Klausuraufgabe", use_container_width=True)
        
        # OCR mit Gemini
        with st.spinner("Lese Text mit Gemini Flash..."):
            ocr_text = extract_text_with_gemini(image)
            
        # Debug: OCR-Ergebnis anzeigen
        if debug_mode:
            st.markdown("### OCR-Ergebnis:")
            st.code(ocr_text)
        
        # Lösungen mit Claude
        with st.spinner("Löse Aufgaben mit Claude 4 Opus..."):
            result = solve_with_claude(ocr_text, use_knowledge)
        
        # Ergebnisse anzeigen
        st.markdown("---")
        st.markdown("###Lösungen:")
        
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
                    st.markdown(f"_{line}_")
                else:
                    st.markdown(line)
                    
    except Exception as e:
        st.error(f"❌ Fehler: {str(e)}")
        st.info("Stelle sicher, dass das Bild klar lesbar ist.")

# --- Footer ---
st.markdown("---")
st.caption("Made by Fox & Gemini Flash OCR + Claude 4 Opus")
