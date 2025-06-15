import streamlit as st
from google.oauth2 import service_account
from googleapiclient.discovery import build
from PIL import Image
import google.generativeai as genai
from anthropic import Anthropic
import io
import zipfile
import logging

# Key-Validierungstest +++
from anthropic import Anthropic

def test_claude_key(api_key):
    try:
        client = Anthropic(api_key=api_key)
        models = client.models.list()
        available_models = [model.id for model in models]
        st.session_state.claude_models = available_models  # Für spätere Nutzung speichern
        return True, available_models
    except Exception as e:
        return False, str(e)
        
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

    # +++ NEU: Claude Key Live-Test +++
    if "claude_key" in st.secrets and not invalid:
        is_valid, models_or_error = test_claude_key(st.secrets["claude_key"])
        if not is_valid:
            invalid.append(f"Claude (API Fehler: {models_or_error}")
        elif "claude-3-opus-20240229" not in models_or_error:
            invalid.append("Claude 3 Opus nicht verfügbar")

    if missing:
        st.error(f"Fehlende API Keys: {', '.join(missing)}")
    if invalid:
        st.error(f"Probleme mit: {', '.join(invalid)}")
        with st.expander("Details zur Claude-Key-Überprüfung"):
            if "claude_models" in st.session_state:
                st.write("Verfügbare Modelle:", st.session_state.claude_models)
            else:
                st.write("Keine Modelldaten verfügbar")
    if missing or invalid:
        st.stop()

# --- UI-Einstellungen ---
st.set_page_config(layout="centered")
st.title("🦊 Koifox-Bot")

# +++ Key-Validierung mit Live-Test +++
validate_keys()  # Enthält jetzt den Claude-Test

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

# --- Kombinierter Accounting Prompt (Original + Optimierungen) ---
ACCOUNTING_PROMPT = """
You are a highly qualified accounting expert with PhD-level knowledge of advanced university courses in accounting and finance. Your task is to answer questions in this domain precisely and without error.

### STRICT RULES:
1. **SOURCE BINDING**: Use ONLY the provided knowledge archive (university scripts). Never external methods!
2. **EXAM FORMAT**: For each question:
   - Identify question number (e.g., "Task 6")
   - Extract ALL numbers and options (A/B/C)
   - Follow the EXACT solution method from scripts
3. **MULTI-TASK HANDLING**: When multiple questions are detected:
   - Process each separately
   - Number solutions (Task 1, Task 2...)
   - Use the official format from past exams

### OUTPUT FORMAT:
<task nr="X">
<question>FULL question text</question>
<method>Script method used (e.g., "Grenzplankostenrechnung p.45")</method>
<solution>
Step-by-step calculation
</solution>
<answer>Final answer (Letter + Value)</answer>
</task>

### THEORETICAL SCOPE (ORIGINAL):
• Cost-type, cost-center and cost-unit accounting
• Full/variable/marginal costing systems
• Flexible and Grenzplankostenrechnung
• Contribution-margin accounting
• Business-economics MRS convention
• Activity-analysis models
• Contribution-based pricing

### CRITICAL:
- If uncertain: "No matching method found in scripts"
- NEVER deviate from script solutions!
- 100% consistency with university standards
"""

# --- Bildverarbeitung mit Vorverarbeitung ---
try:
    uploaded_file = st.file_uploader(
        "**Choose an exam paper image...**\n\nDrag and drop file here\nLimit 200MB per file - PNG, JPG, JPEG, WEBP, BMP",
        type=["png", "jpg", "jpeg", "webp", "bmp"],
        key="file_uploader"  # Wichtig für Session-Stability
    )

    if uploaded_file is not None:  # Explizite None-Prüfung
        try:
            # 1. Bildvalidierung  
            image = Image.open(uploaded_file)
            image.verify()
            image = Image.open(uploaded_file)  # Neu öffnen nach verify()
            
            # 2. Bildoptimierung
            from PIL import ImageOps, ImageFilter
            preprocessed_image = (
                image.convert('L')
                .point(lambda x: 0 if x < 100 else 255)
                .filter(ImageFilter.SHARPEN)
                .filter(ImageFilter.SMOOTH_MORE)
            )
            
        # Debug-Anzeige
        col1, col2 = st.columns(2)
        with col1:
            st.image(image, caption="Original", use_column_width=True)
        with col2:
            st.image(preprocessed_image, caption="Optimized", use_column_width=True)

        # 2. Hochpräzise OCR
        with st.spinner("Analysiere Dokument..."):
            response = vision_model.generate_content(
                [
                    "Extract ALL exam tasks with:",
                    "1. Complete question text",
                    "2. All numbers and options (A/B/C...)",
                    "3. Formulas and calculation steps",
                    "Format: 'Task X: [Question] | Options: A)... B)...'",
                    preprocessed_image
                ],
                generation_config={
                    "temperature": 0,  # Maximale Deterministik
                    "top_p": 0.3,
                    "max_output_tokens": 4000
                }
            )
            extracted_text = response.text

        # 3. Claude-Antwortgenerierung
        if extracted_text:
            client = Anthropic(api_key=st.secrets["claude_key"])
            response = client.messages.create(
                model="claude-3-opus-20240229",
                messages=[
                    {
                        "role": "user",
                        "content": f"""
                        {ACCOUNTING_PROMPT}
                        
                        <DOCUMENT>
                        {extracted_text}
                        </DOCUMENT>
                        
                        <KNOWLEDGE_BASE>
                        {st.session_state.get('drive_knowledge', '')}
                        </KNOWLEDGE_BASE>
                        
                        Instructions:
                        1. Solve ALL tasks sequentially
                        2. Strictly follow script methods
                        3. Use German accounting terminology
                        """
                    }
                ],
                temperature=0,
                seed=12345,
                max_tokens=4000
            )
            
            # Antwortformatierung
            answer_content = response.content[0].text
            if "<task nr=" in answer_content:
                st.markdown("### Expert Solution:")
                st.markdown(answer_content, unsafe_allow_html=True)
            else:
                st.markdown("### Answer:")
                st.markdown(answer_content)

    except Exception as e:
            st.error(f"Bildverarbeitungsfehler: {str(e)}")
            logger.error(f"Image processing failed: {str(e)}")
            st.stop()

except NameError as e:
    st.error("Initialisierungsfehler. Bitte Seite neu laden.")
    logger.critical(f"NameError occurred: {str(e)}")
    raise st.StopException
except Exception as e:
    st.error("Unerwarteter Fehler. Bitte Support kontaktieren.")
    logger.error(f"Unexpected error: {str(e)}")
    st.stop()
