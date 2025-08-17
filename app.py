import streamlit as st
from openai import OpenAI, OpenAIError
from PIL import Image, ImageEnhance
import logging
import io
import base64
import pdf2image
import os
import pillow_heif

# --- VORBEREITUNG ---

st.markdown(f'''
<!-- Apple Touch Icon -->
<link rel="apple-touch-icon" sizes="180x180" href="https://em-content.zobj.net/thumbs/120/apple/325/fox-face_1f98a.png">
<!-- Web App Meta Tags -->
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="theme-color" content="#FF6600"> 
''', unsafe_allow_html=True)

st.set_page_config(layout="centered", page_title="KFB1", page_icon="🦊")
st.title("🦊 Koifox-Bot 1 ")
st.write("made with deep minimal & love by fox 🚀")

# --- Logger Setup ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- API Key Validation ---
def validate_keys():
    if "openai_key" not in st.secrets or not st.secrets["openai_key"].startswith("sk-"):
        st.error("API Key Problem: 'openai_key' in Streamlit Secrets fehlt oder ist ungültig.")
        st.stop()
validate_keys()

# --- API Client Initialisierung ---
try:
    openai_client = OpenAI(api_key=st.secrets["openai_key"])
except Exception as e:
    st.error(f"❌ Fehler bei der Initialisierung des OpenAI-Clients: {str(e)}")
    st.stop()

# --- BILDVERARBEITUNG & OPTIMIERUNG ---
def process_and_prepare_image(uploaded_file):
    # Diese Funktion ist exakt identisch mit der Gemini-Version für einen fairen Vergleich.
    try:
        pillow_heif.register_heif_opener()
        file_extension = os.path.splitext(uploaded_file.name)[1].lower()
        if file_extension in ['.png', '.jpeg', '.jpg', '.gif', '.webp', '.heic']:
            image = Image.open(uploaded_file)
        elif file_extension == '.pdf':
            pages = pdf2image.convert_from_bytes(uploaded_file.read(), fmt='jpeg', dpi=300)
            if not pages:
                st.error("❌ Konnte keine Seite aus dem PDF extrahieren.")
                return None
            image = pages[0]
        else:
            st.error(f"❌ Nicht unterstütztes Format: {file_extension}.")
            return None
        if image.mode in ("RGBA", "P", "LA"):
            image = image.convert("RGB")
        image_gray = image.convert('L')
        enhancer = ImageEnhance.Contrast(image_gray)
        image_enhanced = enhancer.enhance(1.5)
        final_image = image_enhanced.convert('RGB')
        return final_image
    except Exception as e:
        logger.error(f"Fehler bei der Bildverarbeitung: {str(e)}")
        return None

# --- GPT-5 Solver ---
def solve_with_gpt(image):
    try:
        logger.info("Bereite Anfrage für GPT-5 vor")
        with io.BytesIO() as output:
            image.save(output, format="JPEG", quality=85)
            img_bytes = output.getvalue()
        img_base64 = base64.b64encode(img_bytes).decode('utf-8')
        
        system_prompt = """
        [Persona & Wissensbasis]
        Du bist ein wissenschaftlicher Mitarbeiter und Korrektor am Lehrstuhl für Internes Rechnungswesen der Fernuniversität Hagen (Modul 31031). Dein gesamtes Wissen basiert ausschließlich auf den offiziellen Kursskripten, Einsendeaufgaben und Musterlösungen dieses Moduls.
        [Verbot von externem Wissen]
        Ignoriere strikt und ausnahmslos alle Lösungswege, Formeln oder Methoden von anderen Universitäten, aus allgemeinen Lehrbüchern oder von Online-Quellen. Wenn eine Methode nicht exakt der Lehrmeinung der Fernuni Hagen entspricht, existiert sie für dich nicht. Deine Loyalität gilt zu 100% dem Fernuni-Standard.
        [Lösungsprozess]
        1. Analyse: Lies die Aufgabe und die gegebenen Daten (inkl. Graphen) mit äußerster Sorgfalt.
        2. Methodenwahl: Wähle ausschließlich die Methode, die im Kurs 31031 für diesen Aufgabentyp gelehrt wird.
        3. Schritt-für-Schritt-Lösung: Zeige deinen Lösungsweg transparent und nachvollziehbar auf, so wie es in einer Klausur erwartet wird. Benenne die verwendeten Formeln gemäß der Fernuni-Terminologie.
        4. Selbstkorrektur: Überprüfe dein Ergebnis kritisch und frage dich: "Ist dies exakt der Weg, den der Lehrstuhl in einer Musterlösung zeigen würde?"
        [Output-Format]
        Gib deine finale Antwort zwingend im folgenden Format aus. Fasse dich in der Begründung kurz und prägnant.
        Aufgabe [Nr]: [Finales Ergebnis]
        Begründung: [Kurze 1-Satz-Erklärung des Ergebnisses basierend auf der Fernuni-Methode.]
        """

        response = openai_client.chat.completions.create(
            # KORRIGIERT: Festgelegt auf den von dir gefundenen, stabilen Snapshot von GPT-5
            model="gpt-5-2025-08-07",
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Lies die Informationen aus dem bereitgestellten Bild. Löse anschließend die darauf sichtbare Aufgabe gemäß deiner Anweisungen und halte dich strikt an das geforderte Ausgabeformat."},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_base64}", "detail": "high"}}
                    ]
                }
            ],
            temperature=0.1,
            max_tokens=8192 # Angepasst an die großzügigeren Limits neuerer Modelle
        )
        logger.info("Antwort von GPT-5 erhalten.")
        return response.choices[0].message.content
    except OpenAIError as e:
        logger.error(f"OpenAI API Fehler: {str(e)}")
        st.error(f"❌ OpenAI API Fehler: {str(e)}")
        return None
    except Exception as e:
        logger.error(f"Unerwarteter Fehler: {str(e)}")
        st.error(f"❌ Ein unerwarteter Fehler ist aufgetreten: {str(e)}")
        return None

# --- HAUPTINTERFACE ---
debug_mode = st.checkbox("🔍 Debug-Modus", value=False)
uploaded_file = st.file_uploader("**Klausuraufgabe hochladen...**", type=["png", "jpg", "jpeg", "gif", "webp", "pdf", "heic"])
if uploaded_file is not None:
    try:
        processed_image = process_and_prepare_image(uploaded_file)
        if processed_image:
            # (Restlicher Code für die UI bleibt unverändert)
            if "rotation" not in st.session_state: st.session_state.rotation = 0
            if st.button("🔄 Bild drehen"): st.session_state.rotation = (st.session_state.rotation + 90) % 360
            rotated_img = processed_image.rotate(-st.session_state.rotation, expand=True)
            st.image(rotated_img, caption=f"Optimiertes Bild (gedreht um {st.session_state.rotation}°)", use_container_width=True)
            if st.button("🧮 Aufgabe(n) lösen", type="primary"):
                st.markdown("---")
                with st.spinner("GPT-5 analysiert das Bild..."):
                    gpt_solution = solve_with_gpt(rotated_img)
                if gpt_solution:
                    st.markdown("### 🎯 FINALE LÖSUNG")
                    st.markdown(gpt_solution)
                    if debug_mode:
                        with st.expander("🔍 GPT-5 Rohausgabe"): st.code(gpt_solution)
                else:
                    st.error("❌ Keine Lösung generiert")
    except Exception as e:
        logger.error(f"Fehler im Hauptprozess: {str(e)}")
        st.error(f"❌ Ein unerwarteter Fehler ist aufgetreten: {str(e)}")

# Footer
st.markdown("---")
st.caption("Made by Fox & Koi-9 ❤️ | OpenAI GPT-5 (stable)")
