import streamlit as st
from anthropic import Anthropic
from openai import OpenAI
from PIL import Image
import google.generativeai as genai
import logging
import hashlib
import re
import io

# --- Logger Setup ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- UI-Einstellungen ---
st.set_page_config(layout="centered", page_title="Koifox-Bot", page_icon="🦊")
st.title("🦊 Koifox-Bot")
st.markdown("*Fernuni Hagen IRW-konformes Multi-Model System*")

# --- API Key Validation ---
def validate_keys():
    required_keys = {
        'gemini_key': ('AIza', "Gemini"),
        'claude_key': ('sk-ant', "Claude"),
        'openai_key': ('sk-', "OpenAI")
    }
    missing = []
    
    for key, (prefix, name) in required_keys.items():
        if key not in st.secrets:
            missing.append(name)
        elif not st.secrets[key].startswith(prefix):
            missing.append(f"{name} (invalid)")
    
    if missing:
        st.error(f"Fehlende API Keys: {', '.join(missing)}")
        st.stop()

validate_keys()

# --- API Clients ---
genai.configure(api_key=st.secrets["gemini_key"])
vision_model = genai.GenerativeModel("gemini-1.5-flash")
claude_client = Anthropic(api_key=st.secrets["claude_key"])
openai_client = OpenAI(api_key=st.secrets["openai_key"])

# --- GPT Model Detection ---
@st.cache_data
def get_available_gpt_model():
    """Testet welches GPT Modell verfügbar ist"""
    test_models = ["gpt-4-turbo", "gpt-4", "gpt-3.5-turbo"]
    
    for model in test_models:
        try:
            response = openai_client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": "Test"}],
                max_tokens=10
            )
            return model
        except:
            continue
    return "gpt-3.5-turbo"

GPT_MODEL = get_available_gpt_model()
st.sidebar.info(f"🤖 Claude + {GPT_MODEL}")

# --- VERBESSERTE OCR ---
@st.cache_data(ttl=3600, show_spinner=False)
def extract_text_with_gemini(_image_bytes, file_hash):
    """Robuste OCR mit Gemini"""
    try:
        logger.info(f"Starting OCR for hash: {file_hash[:8]}...")
        
        image = Image.open(io.BytesIO(_image_bytes))
        
        # Optimale Größe für OCR
        if max(image.width, image.height) > 3000:
            image.thumbnail((3000, 3000), Image.Resampling.LANCZOS)
        
        # Klarer OCR Prompt
        ocr_prompt = """Extrahiere den EXAKTEN Text aus diesem Klausurbild:

1. Lies von oben nach unten ALLES
2. Inkludiere:
   - Aufgabennummern (z.B. "Aufgabe 1", "Aufgabe 2")
   - Komplette Fragestellungen
   - ALLE Antwortoptionen (A, B, C, D, E) mit vollem Text
   - "(x aus 5)" Angaben
   - Alle Zahlen und Formeln

WICHTIG: 
- Füge KEINE eigenen Kommentare hinzu
- Keine Interpretation
- Nur der reine Text aus dem Bild"""
        
        response = vision_model.generate_content(
            [ocr_prompt, image],
            generation_config={
                "temperature": 0,
                "max_output_tokens": 12000
            }
        )
        
        ocr_text = response.text.strip()
        
        # Entferne falsche Statusmeldungen
        ocr_text = re.sub(r'(Graph|Table|Formel|Data):\s*(Kein|No|Not found|Keine).*?(vorhanden|found)\.?\s*', '', ocr_text, flags=re.IGNORECASE)
        ocr_text = re.sub(r'❌\s*Keine Aufgaben.*?gefunden!?\s*', '', ocr_text)
        ocr_text = re.sub(r'✅\s*Graphen oder.*?gefunden!?\s*', '', ocr_text)
        
        logger.info(f"OCR completed: {len(ocr_text)} characters")
        return ocr_text
        
    except Exception as e:
        logger.error(f"OCR Error: {str(e)}")
        raise e

# --- VERBESSERTE ANTWORTEXTRAKTION ---
def extract_structured_solution(solution_text):
    """Extrahiert sowohl Antworten als auch Begründungen strukturiert"""
    result = {}
    
    # Teile Text in Zeilen
    lines = solution_text.split('\n')
    current_task = None
    current_answer = None
    current_reasoning = []
    
    for line in lines:
        line = line.strip()
        
        # Erkenne Aufgabe
        task_match = re.match(r'Aufgabe\s*(\d+)\s*:\s*([A-E]+)', line, re.IGNORECASE)
        if task_match:
            # Speichere vorherige Aufgabe
            if current_task and current_answer:
                result[f"Aufgabe {current_task}"] = {
                    'answer': current_answer,
                    'reasoning': ' '.join(current_reasoning).strip()
                }
            
            # Neue Aufgabe
            current_task = task_match.group(1)
            current_answer = ''.join(sorted(c for c in task_match.group(2).upper() if c in 'ABCDE'))
            current_reasoning = []
        
        # Erkenne Begründung
        elif line.startswith('Begründung:'):
            reasoning_text = line.replace('Begründung:', '').strip()
            if reasoning_text:
                current_reasoning = [reasoning_text]
        
        # Fortsetzung der Begründung
        elif current_task and line and not line.startswith('Aufgabe'):
            current_reasoning.append(line)
    
    # Letzte Aufgabe speichern
    if current_task and current_answer:
        result[f"Aufgabe {current_task}"] = {
            'answer': current_answer,
            'reasoning': ' '.join(current_reasoning).strip()
        }
    
    return result

# --- Claude Solver mit Fernuni-Fokus ---
def solve_with_claude(ocr_text, previous_feedback=None):
    """Claude löst strikt nach Fernuni-Standards"""
    
    prompt = f"""

{f"WICHTIGER HINWEIS VON ANDEREM MODELL: {previous_feedback}" if previous_feedback else ""}

You are a highly qualified accounting expert with PhD-level 
knowledge of the university course "Internes Rechnungswesen (31031)" at Fernuniversität Hagen. 
Your task is to answer exam questions with 100% accuracy.

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

WICHTIG: Analysiere NUR den folgenden OCR-Text. Erfinde KEINE anderen Aufgaben! 
Sei extrem präzise und verwende die Lösungswege und die Terminologie der Fernuni Hagen. Es gibt absolut keinen Raum für Fehler!

OCR-TEXT START:
{ocr_text}
OCR-TEXT ENDE

KRITISCHE ANWEISUNGEN:
1. Lies die Aufgabe SEHR sorgfältig
2. Bei Rechenaufgaben:
   - Zeige JEDEN Rechenschritt
   - Prüfe dein Ergebnis nochmal
3. Bei Multiple Choice: Prüfe jede Option einzeln
4. VERIFIZIERE deine Antwort bevor du antwortest
5. Stelle SICHER, dass deine Antwort mit deiner Analyse übereinstimmt!

FORMAT - WICHTIG:
Aufgabe [Nr]: [NUR die finale Antwort - Zahl oder Buchstabe(n)]
Begründung: [1 Satz auf Deutsch]"""

    response = claude_client.messages.create(
        model="claude-4-opus-20250514",
        max_tokens=3000,
        temperature=0.1,
        system="Du bist ein Fernuni Hagen Experte für Modul 31031. Verwende AUSSCHLIESSLICH Fernuni-Definitionen.",
        messages=[{"role": "user", "content": prompt}]
    )
    
    return response.content[0].text

# --- GPT Solver mit Fernuni-Fokus ---
def solve_with_gpt(ocr_text, previous_feedback=None):
    """GPT löst strikt nach Fernuni-Standards"""
    
    prompt = f"""

DEINE AUFGABE:

{f"WICHTIGER HINWEIS VON ANDEREM MODELL: {previous_feedback}" if previous_feedback else ""}

You are a highly qualified accounting expert with PhD-level 
knowledge of the university course "Internes Rechnungswesen (31031)" at Fernuniversität Hagen. 
Your task is to answer exam questions with 100% accuracy.

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

WICHTIG: Analysiere NUR den folgenden OCR-Text. Erfinde KEINE anderen Aufgaben! 
Sei extrem präzise und verwende die Lösungswege und die Terminologie der Fernuni Hagen. Es gibt absolut keinen Raum für Fehler!

OCR-TEXT START:
{ocr_text}
OCR-TEXT ENDE

KRITISCHE ANWEISUNGEN:
1. Lies die Aufgabe SEHR sorgfältig
2. Bei Rechenaufgaben:
   - Zeige JEDEN Rechenschritt
   - Prüfe dein Ergebnis nochmal
3. Bei Multiple Choice: Prüfe jede Option einzeln
4. VERIFIZIERE deine Antwort bevor du antwortest
5. Stelle SICHER, dass deine Antwort mit deiner Analyse übereinstimmt!

FORMAT - WICHTIG:
Aufgabe [Nr]: [NUR die finale Antwort - Zahl oder Buchstabe(n)]
Begründung: [1 Satz auf Deutsch]"""

    response = openai_client.chat.completions.create(
        model=GPT_MODEL,
        messages=[
            {"role": "system", "content": "Du bist ein höchstqualifizierter Experte für das Modul 31031 der Fernuniversität Hagen. Verwende AUSSCHLIESSLICH Fernuni-Definitionen."},
            {"role": "user", "content": prompt}
        ],
        max_tokens=3000,
        temperature=0.1
    )
    
    return response.choices[0].message.content

# --- VERBESSERTE KONFLIKTLÖSUNG ---
def resolve_conflicts_improved(ocr_text, claude_sol, gpt_sol, max_iterations=2):
    """Verbesserte Konfliktlösung mit strukturierter Anzeige"""
    
    # Zeige beide initiale Lösungen
    st.markdown("### 🔄 Initiale Lösungen:")
    
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**Claude:**")
        st.code(claude_sol, language=None)
    with col2:
        st.markdown(f"**{GPT_MODEL}:**")
        st.code(gpt_sol, language=None)
    
    # Extrahiere strukturierte Lösungen
    claude_structured = extract_structured_solution(claude_sol)
    gpt_structured = extract_structured_solution(gpt_sol)
    
    st.markdown("### 🔍 Strukturierter Antwortvergleich:")
    st.write(f"**Claude:** {[(task, data['answer']) for task, data in claude_structured.items()]}")
    st.write(f"**GPT:** {[(task, data['answer']) for task, data in gpt_structured.items()]}")
    
    # Prüfe auf Unterschiede
    all_tasks = set(claude_structured.keys()) | set(gpt_structured.keys())
    discrepancies = []
    
    for task in all_tasks:
        claude_ans = claude_structured.get(task, {}).get('answer', '')
        gpt_ans = gpt_structured.get(task, {}).get('answer', '')
        if claude_ans != gpt_ans:
            discrepancies.append(f"{task}: Claude='{claude_ans}' vs GPT='{gpt_ans}'")
    
    if not discrepancies:
        st.success("✅ Konsens erreicht!")
        return True, claude_structured
    
    st.warning(f"⚠️ Unterschiede gefunden: {discrepancies}")
    
    # Iterationen
    current_claude = claude_sol
    current_gpt = gpt_sol
    
    for iteration in range(max_iterations):
        st.markdown(f"### 🔄 Iteration {iteration + 2}:")
        
        feedback = f"""
ACHTUNG: Diskrepanz mit anderem Modell:
{chr(10).join(discrepancies)}

PRÜFE ERNEUT UND MIT EXTREMER SORGFALT UND ABSOLUT AKKURAT ENTSPRECHEND DES MODULS "INTERNES RECHNUNGSWESEN" DER FERNUNIVERSITÄT HAGEN!
"""
        
        # Neue Versuche
        with st.spinner(f"Iteration {iteration + 2} läuft..."):
            current_claude = solve_with_claude(ocr_text, feedback)
            current_gpt = solve_with_gpt(ocr_text, feedback)
        
        # Zeige neue Antworten
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**Claude (neu):**")
            st.code(current_claude, language=None)
        with col2:
            st.markdown(f"**{GPT_MODEL} (neu):**")
            st.code(current_gpt, language=None)
        
        # Prüfe erneut
        claude_structured = extract_structured_solution(current_claude)
        gpt_structured = extract_structured_solution(current_gpt)
        
        st.write(f"**Claude:** {[(task, data['answer']) for task, data in claude_structured.items()]}")  
        st.write(f"**GPT:** {[(task, data['answer']) for task, data in gpt_structured.items()]}")
        
        discrepancies = []
        for task in all_tasks:
            claude_ans = claude_structured.get(task, {}).get('answer', '')
            gpt_ans = gpt_structured.get(task, {}).get('answer', '')
            if claude_ans != gpt_ans:
                discrepancies.append(f"{task}: Claude='{claude_ans}' vs GPT='{gpt_ans}'")
        
        if not discrepancies:
            st.success("✅ Konsens erreicht!")
            return True, claude_structured
        
        st.warning(f"⚠️ Immer noch Unterschiede: {discrepancies}")
    
    st.error("❌ Kein Konsens nach allen Iterationen!")
    return False, (claude_structured, gpt_structured)

# --- MAIN UI ---
uploaded_file = st.file_uploader(
    "**Klausuraufgabe hochladen**",
    type=["png", "jpg", "jpeg"]
)

if uploaded_file is not None:
    # Bild anzeigen
    image = Image.open(uploaded_file)
    st.image(image, caption="Klausuraufgabe", use_container_width=True)
    
    # OCR
    file_bytes = uploaded_file.getvalue()
    file_hash = hashlib.md5(file_bytes).hexdigest()
    
    with st.spinner("Lese Text..."):
        try:
            ocr_text = extract_text_with_gemini(file_bytes, file_hash)
            
            # Validierung
            if len(ocr_text) < 100:
                st.error("❌ OCR zu kurz - bitte besseres Bild verwenden")
                st.stop()
            
            # Aufgaben finden
            found_tasks = re.findall(r'Aufgabe\s+(\d+)', ocr_text, re.IGNORECASE)
            if found_tasks:
                st.success(f"✅ Gefunden: Aufgabe {', '.join(set(found_tasks))}")
            
        except Exception as e:
            st.error(f"❌ OCR Fehler: {str(e)}")
            st.stop()
    
    # OCR anzeigen
    with st.expander("OCR-Text"):
        st.text(ocr_text)
    
    # Lösen
    if st.button("🧮 Nach Fernuni-Standards lösen", type="primary"):
        st.markdown("---")
        
        try:
            # Erste Lösungen
            with st.spinner("Generiere Lösungen..."):
                claude_solution = solve_with_claude(ocr_text)
                gpt_solution = solve_with_gpt(ocr_text)
            
            # Konfliktlösung mit voller Transparenz
            consensus, result = resolve_conflicts_improved(ocr_text, claude_solution, gpt_solution)
            
            st.markdown("---")
            st.markdown("### 🎯 FINALE LÖSUNG:")
            
            if consensus:
                # Zeige strukturierte finale Antwort
                for task, data in result.items():
                    st.markdown(f"### {task}: **{data['answer']}**")
                    if data['reasoning']:
                        st.markdown(f"*Begründung: {data['reasoning']}*")
                    st.markdown("")  # Leerzeile
            else:
                st.error("❌ Finale Uneinigkeit - manuelle Prüfung erforderlich!")
                
                # Zeige beide finalen Strukturen
                claude_final, gpt_final = result
                
                col1, col2 = st.columns(2)
                with col1:
                    st.markdown("**Claude Final:**")
                    for task, data in claude_final.items():
                        st.markdown(f"**{task}: {data['answer']}**")
                        st.caption(data['reasoning'][:100] + "..." if len(data['reasoning']) > 100 else data['reasoning'])
                
                with col2:
                    st.markdown("**GPT Final:**")
                    for task, data in gpt_final.items():
                        st.markdown(f"**{task}: {data['answer']}**")
                        st.caption(data['reasoning'][:100] + "..." if len(data['reasoning']) > 100 else data['reasoning'])
                
        except Exception as e:
            st.error(f"Fehler: {str(e)}")
            st.exception(e)

# Footer
st.markdown("---")
st.caption("Fernuni Hagen konformes System | Strikt nach Modul 31031 Standards")
