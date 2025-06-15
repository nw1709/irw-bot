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
    
    if missing or invalid:
        st.error(f"API Key Problem: Missing {', '.join(missing)} | Invalid {', '.join(invalid)}")
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
        logger.error(f"Drive Error: {str(e)}")

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
        logger.error(f"Knowledge Load Error: {str(e)}")
        st.session_state.drive_knowledge = ""

# --- Gemini 1.5 Flash Konfiguration ---
genai.configure(api_key=st.secrets["gemini_key"])
vision_model = genai.GenerativeModel("gemini-1.5-flash")

# --- Hybrid Accounting Prompt ---
ACCOUNTING_PROMPT = """
You are a highly qualified accounting expert with PhD-level knowledge of advanced university courses 
in accounting and finance. Your task is to answer examns questions with 100% accuracy and without error using the provided materials.
 
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
• Marketing segmentation, price-elasticity, contribution-based pricing & mix planning Do not apply IFRS/GAAP valuation, 
classical micro-economic MRS, or any other external doctrines unless the task explicitly demands them.
 
Read the question extremely carefully. Pay special attention to avoid any errors in visual interpretation.
Analyse the question step by step in your mind. Think thoroughly before answering to ensure your response is correct.
It is crucial that your answer is CORRECT—there is no room for error.

Provide answers in EXACTLY this format:

### OUTPUT FORMAT:
**Task [X]**  
[Complete answer as required by the task]  

<details>
<summary>🔍 Detailed Solution (Click to expand)</summary>

**Question:**  
[Full question text]  

**Script Reference:**  
[Exact script location, e.g., "Controlling Skript S.72"]  

**Methodology:**  
[Explanation of used method]  

**Step-by-Step:**  
1. Step 1...
2. Step 2... 

**Verification:**  
[Cross-check with knowledge base]  
</details>

### STRICT RULES:
1. PRIMARY ANSWER: Show ONLY what the task requires first
2. Put ALL explanations, calculations and references in details section
3. Use German for technical terms
4. Preserve original question formatting
5. For open-ended questions: Provide 1-sentence summary first
"""

# --- Antwortverarbeitung ---
if extracted_text:
    client = Anthropic(api_key=st.secrets["claude_key"])
    response = client.messages.create(
        model="claude-3-opus-20240229",
        messages=[{
            "role": "user",
            "content": f"{ACCOUNTING_PROMPT}\n\nDOCUMENT:\n{extracted_text}\n\nKNOWLEDGE:\n{st.session_state.get('drive_knowledge', '')}"
        }],
        temperature=0,
        max_tokens=4000
    )
    
    # Intelligente Antwortverarbeitung
    answer_content = response.content[0].text
    
    # Task-basierte Aufteilung
    task_blocks = []
    current_task = []
    
    for line in answer_content.split('\n'):
        if line.startswith('**Task'):
            if current_task:
                task_blocks.append('\n'.join(current_task))
                current_task = []
        current_task.append(line)
    if current_task:
        task_blocks.append('\n'.join(current_task))
    
    # Anzeige mit Expander
    for block in task_blocks:
        if not block.strip():
            continue
            
        # Extrahiere Hauptantwort (erste Zeilen vor details-Tag)
        main_answer = []
        details_section = []
        in_details = False
        
        for line in block.split('\n'):
            if '<details>' in line:
                in_details = True
            if not in_details and line.strip():
                main_answer.append(line)
            else:
                details_section.append(line)
                
        st.markdown('\n'.join(main_answer))
        
        # Details-Section mit verbessertem Parsing
        if details_section:
            details_content = '\n'.join(details_section)
            with st.expander("📚 Detailed Solution"):
                # Entferne HTML-Tags falls vorhanden
                clean_details = details_content.replace('<details>', '').replace('</details>', '')
                st.markdown(clean_details, unsafe_allow_html=True)
"""

# --- Bildverarbeitung ---
try:
    uploaded_file = st.file_uploader(
        "**Klausuraufgabe hochladen...**\n\n(PNG/JPG/JPEG, max. 200MB)",
        type=["png", "jpg", "jpeg"],
        key="file_uploader"
    )

    if uploaded_file is not None:
        try:
            # Bild anzeigen (ohne Vorverarbeitung)
            image = Image.open(uploaded_file)
            st.image(image, caption="Hochgeladenes Dokument", use_container_width=True)

            # OCR mit Gemini
            with st.spinner("Analysiere Klausuraufgaben..."):
                response = vision_model.generate_content(
                    [
                        "Extract ALL exam tasks with:",
                        "1. Complete question text",
                        "2. All numbers and options (A/B/C...)",
                        "3. Formulas and tables",
                        "Format: 'TASK X: [Question] | OPTIONS: A)... B)...'",
                        image
                    ],
                    generation_config={
                        "temperature": 0,
                        "max_output_tokens": 4000
                    }
                )
                extracted_text = response.text

# --- Claude Analyse ---
if extracted_text:
    client = Anthropic(api_key=st.secrets["claude_key"])
    response = client.messages.create(
        model="claude-3-opus-20240229",
        max_tokens=4000,
        messages=[{
            "role": "user",
            "content": f"""
            {ACCOUNTING_PROMPT}
            
            <EXAM_DOCUMENT>
            {extracted_text}
            </EXAM_DOCUMENT>
            
            <KNOWLEDGE_BASE>
            {st.session_state.get('drive_knowledge', '')}
            </KNOWLEDGE_BASE>
            """
        }],
        temperature=0
    )

    # Antwortformatierung
    answer_content = response.content[0].text
    st.markdown("### Lösungen:")
    st.markdown(answer_content)

        except Exception as e:
            st.error(f"Verarbeitungsfehler: {str(e)}")
            logger.error(f"Processing Error: {str(e)}")

except Exception as e:
    st.error(f"Systemfehler: {str(e)}")
    logger.critical(f"System Error: {str(e)}")
