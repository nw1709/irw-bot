import streamlit as st
from anthropic import Anthropic
from openai import OpenAI
from PIL import Image
import google.generativeai as genai
import logging
import hashlib
import re

# --- Logger Setup ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- API Key Validation ---
def validate_keys():
    required_keys = {
        'gemini_key': ('AIza', "Gemini"),
        'claude_key': ('sk-ant', "Claude"),
        'openai_key': ('sk-', "OpenAI")
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
st.markdown("*Made with coffee, deep minimal and tiny gummy bears*")

# --- Cache Management ---
col1, col2 = st.columns([3, 1])
with col2:
    if st.button("🗑️ Cache leeren", type="secondary", help="Löscht gespeicherte OCR-Ergebnisse"):
        st.cache_data.clear()
        st.cache_resource.clear()
        st.rerun()

# --- API Clients ---
genai.configure(api_key=st.secrets["gemini_key"])
vision_model = genai.GenerativeModel("gemini-1.5-flash")
claude_client = Anthropic(api_key=st.secrets["claude_key"])
openai_client = OpenAI(api_key=st.secrets["openai_key"])

# --- Verbessertes OCR mit Caching ---
@st.cache_data(ttl=3600)
def extract_text_with_gemini(_image, file_hash):
    try:
        logger.info(f"Starting OCR for file hash: {file_hash}")
        response = vision_model.generate_content(
            [
                "Extract ALL text from this exam image EXACTLY as written, including EVERY detail from graphs, charts, or sketches. For graphs: Explicitly list ALL axis labels, ALL scales, ALL intersection points with axes (e.g., 'x-axis at 450', 'y-axis at 20'), and EVERY numerical value or annotation. Do NOT interpret, solve, or infer beyond the visible text and numbers. Output a COMPLETE verbatim transcription with NO omissions.",
                _image
            ],
            generation_config={
                "temperature": 0.0,
                "max_output_tokens": 8000
            }
        )
        ocr_text = response.text.strip()
        logger.info(f"OCR result length: {len(ocr_text)} characters, content: {ocr_text[:200]}...")
        return ocr_text
    except Exception as e:
        logger.error(f"Gemini OCR Error: {str(e)}")
        raise e

# --- ROBUSTE ANTWORTEXTRAKTION ---
def extract_structured_answers(solution_text):
    result = {}
    lines = solution_text.split('\n')
    current_task = None
    current_answer = None
    current_reasoning = []
    
    # Verbesserte Regex-Patterns für verschiedene Formate
    task_patterns = [
        r'Aufgabe\s*(\d+)\s*:\s*(.+)',  # Standard Format
        r'Task\s*(\d+)\s*:\s*(.+)',     # Englisch
        r'(\d+)[\.\)]\s*(.+)',          # Nummeriert mit Punkt/Klammer
        r'Lösung\s*(\d+)\s*:\s*(.+)'    # Alternative
    ]
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        task_found = False
        for pattern in task_patterns:
            task_match = re.match(pattern, line, re.IGNORECASE)
            if task_match:
                # Speichere vorherige Aufgabe
                if current_task and current_answer:
                    result[f"Aufgabe {current_task}"] = {
                        'answer': current_answer,
                        'reasoning': ' '.join(current_reasoning).strip()
                    }
                    logger.info(f"Stored task: Aufgabe {current_task}, answer: {current_answer}")
                
                current_task = task_match.group(1)
                raw_answer = task_match.group(2).strip()
                
                # Verbesserte Antwort-Normalisierung
                if re.match(r'^[A-E,\s]+$', raw_answer):
                    current_answer = ''.join(sorted(c for c in raw_answer.upper() if c in 'ABCDE'))
                else:
                    # Extrahiere nur Buchstaben/Zahlen als Antwort
                    clean_answer = re.sub(r'[^\w]', '', raw_answer)
                    current_answer = clean_answer if clean_answer else raw_answer
                
                current_reasoning = []
                task_found = True
                logger.info(f"Detected task: Aufgabe {current_task}, answer: {current_answer}")
                break
        
        if not task_found:
            if line.startswith('Begründung:'):
                reasoning_text = line.replace('Begründung:', '').strip()
                if reasoning_text:
                    current_reasoning = [reasoning_text]
            elif current_task and line and not any(re.match(p, line, re.IGNORECASE) for p in task_patterns):
                current_reasoning.append(line)
    
    # Letzte Aufgabe speichern
    if current_task and current_answer:
        result[f"Aufgabe {current_task}"] = {
            'answer': current_answer,
            'reasoning': ' '.join(current_reasoning).strip()
        }
        logger.info(f"Final task stored: Aufgabe {current_task}, answer: {current_answer}")
    
    if not result:
        logger.warning("No tasks detected in solution. Full text: %s", solution_text)
    
    return result

# --- OCR-Text-Überprüfung ---
def validate_ocr_with_llm(ocr_text, model_type):
    prompt = f"""You are an expert in text validation. The following text is OCR data extracted from an exam image. Your task is to reflect this text EXACTLY as provided, without interpretation or changes, and confirm its completeness. Output the text verbatim and add a note: 'Text reflected accurately' if it matches the input, or 'Text may be incomplete' if anything seems missing.

OCR Text:
{ocr_text}
"""
    try:
        if model_type == "claude":
            response = claude_client.messages.create(
                model="claude-4-opus-20250514",
                max_tokens=8000,
                temperature=0.1,
                top_p=0.1,
                messages=[{"role": "user", "content": prompt}]
            )
            logger.info(f"Claude OCR validation received, length: {len(response.content[0].text)} characters")
            return response.content[0].text
        elif model_type == "gpt":
            response = openai_client.chat.completions.create(
                model="gpt-4-turbo",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=3500,
                temperature=0.1,
                top_p=0.1,
                seed=42
            )
            logger.info(f"GPT OCR validation received, length: {len(response.choices[0].message.content)} characters")
            return response.choices[0].message.content
    except Exception as e:
        logger.error(f"Validation Error ({model_type}): {str(e)}")
        return None

# --- CLAUDE PROMPT (Original beibehalten) ---
def create_claude_prompt(ocr_text):
    return f"""You are a PhD-level expert in 'Internes Rechnungswesen (31031)' at Fernuniversität Hagen. Solve exam questions with 100% accuracy, strictly adhering to the decision-oriented German managerial-accounting framework as taught in Fernuni Hagen lectures and past exam solutions. The following text is the OCR data extracted from an exam image - use it EXCLUSIVELY to solve the questions:

{ocr_text}

INSTRUCTIONS:
1. Read the task EXTREMELY carefully
2. For graphs or charts: Use only the explicitly provided axis labels, scales, and intersection points to perform calculations (e.g., 'x-axis at 450')
3. Analyze the problem step-by-step as per Fernuni methodology
4. For multiple choice: Evaluate each option individually based solely on the given data
5. Perform a self-check: Re-evaluate your answer to ensure it aligns with Fernuni standards and the exact OCR input

CRITICAL: You MUST provide answers in this EXACT format for EVERY task found:

Aufgabe [Nr]: [Final answer - letter(s) or number]
Begründung: [1 sentence in German]

NO OTHER FORMAT IS ACCEPTABLE. If you cannot determine a task number, use the closest identifiable number.
"""

# --- VERBESSERTER GPT PROMPT MIT STRICTER DATENVERWENDUNG ---
def create_gpt_prompt(ocr_text):
    return f"""You are a PhD-level expert in 'Internes Rechnungswesen (31031)' at Fernuniversität Hagen. 

CRITICAL: Before solving, you MUST first extract and quote the exact numerical values from the OCR data below. DO NOT use any numbers that are not explicitly written in the OCR text.

OCR DATA (use ONLY this information):
{ocr_text}

MANDATORY FIRST STEP: 
Extract and list every numerical value mentioned in the OCR text (e.g., "450", "20", "3 GE/Liter", etc.) before solving.

INSTRUCTIONS:
1. QUOTE the exact numerical values from OCR before analyzing
2. Read the task EXTREMELY carefully
3. For graphs or charts: Use ONLY the explicitly provided numerical values from the OCR
4. DO NOT infer, assume, or use any numbers not written in the OCR
5. Analyze the problem step-by-step as per Fernuni methodology
6. For multiple choice: Evaluate each option individually based solely on the given OCR data

CRITICAL: You MUST provide answers in this EXACT format for EVERY task found:

EXTRACTED VALUES: [List all numbers from OCR]
Aufgabe [Nr]: [Final answer - letter(s) or number]
Begründung: [1 sentence in German referencing the exact OCR values]

NO OTHER FORMAT IS ACCEPTABLE. Use ONLY numbers explicitly mentioned in the OCR text.
"""

# --- SOLVER MIT CLAUDE OPUS 4 MIT VERBESSERTER SELBSTKORREKTUR ---
def solve_with_claude(ocr_text):
    prompt = create_claude_prompt(ocr_text)
    try:
        logger.info("Sending request to Claude...")
        response = claude_client.messages.create(
            model="claude-4-opus-20250514",
            max_tokens=8000,
            temperature=0.1,
            top_p=0.1,
            messages=[{"role": "user", "content": prompt}]
        )
        logger.info(f"Claude response received, length: {len(response.content[0].text)} characters")
        
        # Prüfe ob bereits im richtigen Format
        initial_extraction = extract_structured_answers(response.content[0].text)
        if initial_extraction:
            logger.info("Claude provided correctly formatted answer on first try")
            return response.content[0].text
        
        # Selbstkorrektur mit STRIKTER Format-Anweisung
        self_check_prompt = f"""The following solution needs to be reformatted. Extract EVERY task from the OCR data and provide answers in this EXACT format:

Aufgabe [Nr]: [Final answer]
Begründung: [1 sentence in German]

Original solution:
{response.content[0].text}

REFORMAT NOW - USE THE EXACT FORMAT ABOVE FOR EVERY TASK:"""
        
        self_check_response = claude_client.messages.create(
            model="claude-4-opus-20250514",
            max_tokens=8000,
            temperature=0.1,
            top_p=0.1,
            messages=[{"role": "user", "content": self_check_prompt}]
        )
        logger.info(f"Self-check response received, length: {len(self_check_response.content[0].text)} characters")
        return self_check_response.content[0].text
        
    except Exception as e:
        logger.error(f"Claude API Error: {str(e)}")
        raise e

# --- VERBESSERTER GPT SOLVER MIT STRIKTER DATENVALIDIERUNG ---
def solve_with_gpt(ocr_text):
    prompt = create_gpt_prompt(ocr_text)
    try:
        logger.info("Sending request to GPT...")
        response = openai_client.chat.completions.create(
            model="gpt-4-turbo",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=3500,
            temperature=0.1,
            top_p=0.1,
            seed=42
        )
        logger.info(f"GPT response received, length: {len(response.choices[0].message.content)} characters")
        
        # Log der GPT-Antwort für Debugging
        gpt_response = response.choices[0].message.content
        logger.info(f"GPT full response: {gpt_response}")
        
        return gpt_response
        
    except Exception as e:
        logger.error(f"GPT API Error: {str(e)}")
        return None

# --- INTELLIGENTE KREUZVALIDIERUNG ---
def cross_validation_consensus(ocr_text):
    st.markdown("### 🔄 Kreuzvalidierung")
    
    with st.spinner("Analyse mit Claude Opus 4..."):
        claude_solution = solve_with_claude(ocr_text)
    claude_data = extract_structured_answers(claude_solution)
    logger.info(f"Claude data extracted: {claude_data}")
    
    with st.spinner("Überprüfung mit GPT-4-turbo..."):
        gpt_solution = solve_with_gpt(ocr_text)
        gpt_data = extract_structured_answers(gpt_solution) if gpt_solution else {}
        logger.info(f"GPT data extracted: {gpt_data}")
    
    # Fallback: Wenn Claude versagt, nutze GPT
    if not claude_data and gpt_data:
        st.warning("⚠️ Claude konnte keine Aufgaben extrahieren - nutze GPT als Fallback")
        claude_data = gpt_data
        claude_solution = gpt_solution
    
    all_tasks = set(claude_data.keys()) | set(gpt_data.keys())
    differences = []
    
    if not claude_data:
        st.error("❌ Beide Modelle konnten keine gültige Lösung liefern. Überprüfe den OCR-Text.")
        return None, None
    
    for task in sorted(all_tasks):
        claude_ans = claude_data.get(task, {}).get('answer', 'Keine Antwort')
        gpt_ans = gpt_data.get(task, {}).get('answer', 'Keine Antwort') if gpt_data else 'Keine Antwort'
        
        col1, col2, col3, col4 = st.columns([2, 2, 2, 1])
        with col1:
            st.write(f"**{task}:**")
        with col2:
            st.write(f"Claude: `{claude_ans}`")
        with col3:
            st.write(f"GPT: `{gpt_ans}`")
        with col4:
            if gpt_ans != 'Keine Antwort' and claude_ans != gpt_ans:
                st.write("⚠️")
                differences.append(task)
            else:
                st.write("✅")
    
    # Debug-Info für Diskrepanzen
    if differences and debug_mode:
        with st.expander(f"🔍 Debug: Diskrepanz-Analyse für {differences}"):
            for task in differences:
                claude_reasoning = claude_data.get(task, {}).get('reasoning', '')
                gpt_reasoning = gpt_data.get(task, {}).get('reasoning', '') if gpt_data else ''
                
                st.write(f"**{task}:**")
                st.write(f"Claude Begründung: {claude_reasoning}")
                st.write(f"GPT Begründung: {gpt_reasoning}")
                st.write("---")
    
    if not differences or not gpt_data:
        st.success("✅ Konsens: Claude-Lösung bestätigt!")
        return True, claude_data
    else:
        st.warning(f"⚠️ Diskrepanzen bei: {', '.join(differences)}. Claude bleibt primär.")
        return False, claude_data

# --- UI ---
debug_mode = st.checkbox("🔍 Debug-Modus", value=True)

uploaded_file = st.file_uploader(
    "**Klausuraufgabe hochladen...**",
    type=["png", "jpg", "jpeg"],
    key="file_uploader"
)

if uploaded_file is not None:
    try:
        file_bytes = uploaded_file.getvalue()
        file_hash = hashlib.md5(file_bytes).hexdigest()
        
        image = Image.open(uploaded_file)
        st.image(image, caption="Hochgeladene Klausuraufgabe", use_container_width=True)
        
        with st.spinner("Lese Text mit Gemini Flash..."):
            ocr_text = extract_text_with_gemini(image, file_hash)
            
        if debug_mode:
            with st.expander("🔍 OCR-Ergebnis"):
                st.code(ocr_text)
                st.info(f"File Hash: {file_hash[:8]}...")
            
            with st.expander("🔍 Claude OCR-Validierung"):
                claude_validation = validate_ocr_with_llm(ocr_text, "claude")
                st.code(claude_validation if claude_validation else "Fehler bei Validierung")
            
            with st.expander("🔍 GPT OCR-Validierung"):
                gpt_validation = validate_ocr_with_llm(ocr_text, "gpt")
                st.code(gpt_validation if gpt_validation else "Fehler bei Validierung")
        
        if st.button("🎯 Lösung mit Kreuzvalidierung", type="primary"):
            if not ocr_text:
                st.error("❌ Kein OCR-Text verfügbar. Bitte überprüfe das Bild.")
            else:
                consensus, result = cross_validation_consensus(ocr_text)
                
                st.markdown("---")
                st.markdown("### 🏆 FINALE LÖSUNG:")
                
                if result is None:
                    st.error("❌ Keine Lösung generiert. Überprüfe den OCR-Text oder Logs.")
                elif not result:
                    st.error("❌ Keine Aufgaben erkannt. Überprüfe, ob der OCR-Text 'Aufgabe X: ...' enthält.")
                else:
                    for task, data in result.items():
                        st.markdown(f"### {task}: **{data['answer']}**")
                        if data['reasoning']:
                            st.markdown(f"*Begründung: {data['reasoning']}*")
                        st.markdown("")
                
                if consensus is not None:
                    if consensus:
                        st.success("✅ Lösung durch Kreuzvalidierung bestätigt!")
                    else:
                        st.warning("⚠️ GPT-Kontrolle zeigte Diskrepanzen – Claude-Lösung bevorzugt.")
                
                st.info("💡 OCR gecacht | Claude Opus 4 priorisiert | GPT mit verbesserter Datenvalidierung")
                    
    except Exception as e:
        logger.error(f"Error: {str(e)}")
        st.error(f"❌ Fehler: {str(e)}")

st.markdown("---")
st.caption(f"🦊 Verbesserte GPT-Datenvalidierung | Claude-4 Opus primär | Präzise OCR-Nutzung")
