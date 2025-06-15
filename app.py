import streamlit as st
from google.oauth2 import service_account
from googleapiclient.discovery import build
from PIL import Image
import google.generativeai as genai
from anthropic import Anthropic
import io
import zipfile
import logging

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
    
    if missing:
        st.error(f"Fehlende API Keys: {', '.join(missing)}")
    if invalid:
        st.error(f"Ungültige API Keys: {', '.join(invalid)} (sollten mit {prefix} beginnen)")
    if missing or invalid:
        st.stop()

validate_keys()

# --- UI-Einstellungen ---
st.set_page_config(layout="centered")
st.title("🦊 Koifox-Bot")
st.markdown("""
    *This application uses Google's Gemini for OCR and Anthropic's Claude for answering advanced accounting questions.*  
    *Made with coffee, deep minimal and tiny gummy bears*  
""")

# --- Google Drive-Verbindung ---
drive_service = None
if "gdrive_creds" in st.secrets:
    try:
        creds = service_account.Credentials.from_service_account_info(st.secrets["gdrive_creds"])
        drive_service = build("drive", "v3", credentials=creds)
        
        # Ordner- und Dateisuche
        folder = drive_service.files().list(
            q="name='IRW_Bot_Gehirn' and mimeType='application/vnd.google-apps.folder'",
            pageSize=1,
            fields="files(id)"
        ).execute().get('files', [{}])[0]
        
        if folder.get('id'):
            zip_file = drive_service.files().list(
                q=f"'{folder['id']}' in parents and mimeType='application/zip'",
                pageSize=1,
                fields="files(id)"
            ).execute().get('files', [{}])[0]
            
            if zip_file.get('id'):
                st.session_state.drive_file_id = zip_file['id']
    except Exception as e:
        logger.error(f"Drive-Fehler: {str(e)}")

# --- Wissen laden ---
if drive_service and hasattr(st.session_state, 'drive_file_id'):
    try:
        downloaded = drive_service.files().get_media(fileId=st.session_state.drive_file_id).execute()
        with zipfile.ZipFile(io.BytesIO(downloaded)) as zip_ref:
            drive_knowledge = "\n\n".join([
                f.read().decode("utf-8", errors="ignore")
                for file in zip_ref.namelist()
                if file.endswith((".txt", ".pdf"))
            ])
        st.session_state.drive_knowledge = drive_knowledge
    except Exception as e:
        logger.error(f"Wissensladung fehlgeschlagen: {str(e)}")
        st.session_state.drive_knowledge = ""

# --- Gemini 1.5 Flash Konfiguration ---
genai.configure(api_key=st.secrets["gemini_key"])
vision_model = genai.GenerativeModel("gemini-1.5-flash")

# --- Accounting Expert Prompt ---
ACCOUNTING_PROMPT = """
You are a highly qualified accounting expert with PhD-level knowledge of advanced university courses in accounting and finance. Your task is to answer questions in this domain precisely and without error.

THEORETICAL SCOPE
Use only the decision-oriented German managerial-accounting (Controlling) framework.
Include, in particular:

• Cost-type, cost-center and cost-unit accounting (Kostenarten-, Kostenstellen-, Kostenträgerrechnung)
• Full, variable, marginal, standard (Plankosten-) and process/ABC costing systems
• Flexible and Grenzplankostenrechnung variance analysis
• Single- and multi-level contribution-margin accounting and break-even logic
• Causality & allocation (Verursachungs- und Zurechnungsprinzip)
• Business-economics MRS convention (MRS = MP₂ / MP₁ unless stated otherwise)
• Activity-analysis production & logistics models (LP, Standort- & Transportprobleme, Supply-Chain-Planungsmatrix)
• Marketing segmentation, price-elasticity, contribution-based pricing & mix planning

Do not apply IFRS/GAAP valuation, classical micro-economic MRS, or any other external doctrines unless the task explicitly demands them.

Follow these steps to answer the question:

1. Read the question extremely carefully. Pay special attention to avoid any errors in visual interpretation.

2. Repeat the question in your reasoning by writing it down exactly as it appears in the image. Use the provided OCR text:

<OCR_TEXT>
{{OCR_TEXT}}
</OCR_TEXT>

3. Analyse the question step by step in your mind. Think thoroughly before answering to ensure your response is correct.

4. Formulate your answer. It should be short yet complete. It is crucial that your answer is CORRECT—there is no room for error.

5. Check your answer once more for accuracy and completeness.

Your final answer must have the following format:
<answer>
YOUR ANSWER HERE
</answer>
"""

# --- Bildverarbeitung ---
uploaded_file = st.file_uploader(
    "**Choose an exam paper image...**\n\nDrag and drop file here\nLimit 200MB per file - PNG, JPG, JPEG, WEBP, BMP",
    type=["png", "jpg", "jpeg", "webp", "bmp"]
)

if uploaded_file:
    try:
        # Bildvalidierung
        image = Image.open(uploaded_file)
        image.verify()
        image = Image.open(uploaded_file)  # Neu öffnen nach verify()
        st.image(image, caption="Hochgeladenes Bild", width=300)
        
        # OCR mit Gemini 1.5 Flash
        with st.spinner("Analysiere Prüfungsdokument..."):
            response = vision_model.generate_content(
                [
                    "Extrahieren Sie den Text präzise aus diesem Prüfungsdokument. Fokussiere auf:",
                    "1. Zahlen und Rechnungen",
                    "2. Fachbegriffe (Kostenrechnung, Controlling)",
                    "3. Aufgabenstellungen mit (A), (B), (C) Optionen",
                    image
                ],
                generation_config={
                    "temperature": 0.1,
                    "max_output_tokens": 2000
                }
            )
            extracted_text = response.text
        
        # Claude Antwort
        if extracted_text:
            client = Anthropic(api_key=st.secrets["claude_key"])
            response = client.messages.create(
                model="claude-3-opus-20240229",
                max_tokens=4000,
                messages=[
                    {
                        "role": "system",
                        "content": ACCOUNTING_PROMPT
                    },
                    {
                        "role": "user",
                        "content": f"""
                        <OCR_TEXT>
                        {extracted_text}
                        </OCR_TEXT>
                        
                        Hintergrundwissen:
                        {st.session_state.get('drive_knowledge', '')}
                        """
                    }
                ]
            )
            
            # Antwortformatierung
            answer_content = response.content[0].text
            answer = (answer_content.split("<answer>")[1].split("</answer>")[0].strip() 
                     if "<answer>" in answer_content else answer_content)
            
            st.markdown("### Experten-Antwort:")
            st.markdown(answer)
    
    except Exception as e:
        logger.error(f"Verarbeitungsfehler: {str(e)}", exc_info=True)
        st.error("Analyse fehlgeschlagen. Bitte versuchen Sie es mit einem anderen Bild oder kontaktieren Sie den Support.")
        
        # Debug-Info
        with st.expander("Technische Details"):
            st.text(f"Fehlertyp: {type(e).__name__}")
            if hasattr(e, 'response'):
                try:
                    st.json(e.response.json())
                except:
                    st.text(str(e.response)[:500])
