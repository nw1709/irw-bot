import streamlit as st
from anthropic import Anthropic
from PIL import Image
import google.generativeai as genai
import io
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

# --- Debug-Modus ---
debug_mode = st.checkbox("🔍 Debug-Modus", value=True, help="Zeigt OCR-Ergebnis und Prompt")

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
        
        # Button zum Lösen (verhindert automatische Mehrfachausführung)
        if st.button("🧮 Aufgaben lösen", type="primary"):
            
            # Prompt erstellen
            prompt = f"""You are an accounting expert for "Internes Rechnungswesen (31031)" at Fernuniversität Hagen.

WICHTIG: Analysiere NUR den folgenden OCR-Text. Erfinde KEINE anderen Aufgaben!

OCR-TEXT START:
{ocr_text}
OCR-TEXT ENDE

Für JEDE Aufgabe im OCR-Text:
1. Bei Multiple Choice (x aus 5): Prüfe ALLE Optionen A-E einzeln
2. Gib an: Aufgabe [Nr]: [Richtige Buchstabe(n)]
3. Begründung: [1 Satz auf Deutsch]

Antworte auf DEUTSCH!"""

            if debug_mode:
                st.markdown("### 🔍 Claude Prompt:")
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
            st.markdown(result)
                    
    except Exception as e:
        st.error(f"❌ Fehler: {str(e)}")

# --- Footer ---
st.markdown("---")
st.caption("Made by Fox | Debug Mode aktiviert")
