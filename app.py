import streamlit as st
from google.oauth2 import service_account
from googleapiclient.discovery import build
from PIL import Image, ImageOps, ImageFilter
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

# --- Hybrid Accounting Prompt ---
ACCOUNTING_PROMPT = """
You are a highly qualified accounting expert with PhD-level knowledge of advanced university courses in accounting and finance. Your task is to answer exam questions with 100% accuracy using ONLY the provided university scripts.

### STRICT PROTOCOL:
1. **TASK IDENTIFICATION**:
   - Extract question number (e.g., "Task 6")
   - Identify all variables and options (A/B/C/D/E)
   - Mark formulas and calculation steps

2. **SOLUTION PROCESS**:
   a) METHOD: Use EXACTLY the method from scripts (cite page)
   b) CALCULATION: Step-by-step in German accounting format
   c) VERIFICATION: Cross-check with knowledge base

3. **OUTPUT FORMAT**:
<task nr="X">
<question>Full original question</question>
<method>Script reference (e.g., "KLR-Skript S.45")</method>
<calculation>
1. Step 1...
2. Step 2...
</calculation>
<answer>Correct option: [LETTER]) [VALUE]</answer>
</task>

### THEORETICAL SCOPE:
• Kostenarten-/stellen-/trägerrechnung
• Deckungsbeitragsrechnung (ein-/mehrstufig)
• Plankostenrechnung (Grenzplankosten)
• Verursachungsprinzip
• Prozesskostenrechnung

### CRITICAL RULES:
- If script method is unclear: "METHOD_NOT_FOUND_IN_SCRIPTS"
- Never deviate from script calculations
- Use German terminology exclusively
"""

# --- Bildverarbeitung ---
try:
    uploaded_file = st.file_uploader(
        "**Choose an exam paper image...**\n\nDrag and drop file here\nLimit 200MB per file - PNG, JPG, JPEG, WEBP, BMP",
        type=["png", "jpg", "jpeg", "webp", "bmp"],
        key="file_uploader"
    )

    if uploaded_file is not None:
        try:
            # 1. Bildvalidierung und -optimierung
            image = Image.open(uploaded_file)
            image.verify()
            image = Image.open(uploaded_file)
            
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

            # 2. OCR mit Gemini
            with st.spinner("Analyzing document..."):
                response = vision_model.generate_content(
                    [
                        "Extract ALL exam tasks with:",
                        "1. Complete question text",
                        "2. All numbers and options (A/B/C...)",
                        "3. Formulas and calculation steps",
                        "Format: 'TASK X: [Question] | OPTIONS: A)... B)...'",
                        preprocessed_image
                    ],
                    generation_config={
                        "temperature": 0,
                        "top_p": 0.3,
                        "max_output_tokens": 4000
                    }
                )
                extracted_text = response.text

            # 3. Claude Analysis
            if extracted_text:
                client = Anthropic(api_key=st.secrets["claude_key"])
                response = client.messages.create(
                    model="claude-3-opus-20240229",
                    messages=[{
                        "role": "user",
                        "content": f"""
                        {ACCOUNTING_PROMPT}
                        
                        <DOCUMENT>
                        {extracted_text}
                        </DOCUMENT>
                        
                        <KNOWLEDGE_BASE>
                        {st.session_state.get('drive_knowledge', '')}
                        </KNOWLEDGE_BASE>
                        """
                    }],
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
            st.error(f"Processing error: {str(e)}")
            logger.error(f"Image processing failed: {str(e)}")
            st.stop()

except NameError as e:
    st.error("Initialization error. Please reload the page.")
    logger.critical(f"NameError: {str(e)}")
    raise st.StopException
except Exception as e:
    st.error("System error. Please contact support.")
    logger.error(f"System error: {str(e)}")
    st.stop()
