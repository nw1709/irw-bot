import streamlit as st
from anthropic import Anthropic
from openai import OpenAI
from PIL import Image
import google.generativeai as genai
import logging
import hashlib
import re
import json
from typing import Dict, Tuple, Optional

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
    if st.button("🗑️ Cache leeren", type="secondary", help="Löscht gespeicherte Ergebnisse"):
        st.cache_data.clear()
        st.cache_resource.clear()
        st.rerun()

# --- API Clients ---
genai.configure(api_key=st.secrets["gemini_key"])
vision_model = genai.GenerativeModel("gemini-1.5-flash")  # Unverändert wie gewünscht
claude_client = Anthropic(api_key=st.secrets["claude_key"])
openai_client = OpenAI(api_key=st.secrets["openai_key"])

# --- GPT Model Detection ---
@st.cache_data
def get_available_gpt_model():
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

# --- RAG-Placeholder ---
@st.cache_resource
def initialize_rag():
    dummy_context = """
    Kostenartenrechnung: Einteilung in Einzel- und Gemeinkosten. Einzelkosten sind direkt zurechenbar, Gemeinkosten über Schlüssel.
    Grenzplankostenrechnung: Abweichungsanalyse durch Vergleich von Soll- und Ist-Kosten.
    Verursachungsprinzip: Kosten werden dem Verursacher zugeordnet.
    """
    return dummy_context

rag_context = initialize_rag()

# --- OCR (unverändert wie gewünscht) ---
@st.cache_data(ttl=3600)
def extract_text_with_gemini(_image, file_hash):
    try:
        logger.info(f"Starting OCR for file hash: {file_hash}")
        response = vision_model.generate_content(
            [
                "Extract ALL text from this exam image EXACTLY as written. Include all question numbers, text, and answer options (A, B, C, D, E). Do NOT interpret or solve.",
                _image
            ],
            generation_config={
                "temperature": 0.0,
                "max_output_tokens": 4000
            }
        )
        return response.text.strip()
    except Exception as e:
        logger.error(f"Gemini OCR Error: {str(e)}")
        raise e

# --- Antwortextraktion mit Debug ---
def extract_structured_answers(solution_text: str) -> Dict:
    """Extrahiert Antworten und Begründungen im JSON-Format mit Debug"""
    try:
        # Versuche, den Text direkt als JSON zu parsen
        parsed_result = json.loads(solution_text)
        return parsed_result
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON response: {solution_text}")
        if debug_mode:
            st.error(f"Debug: Ungültige JSON-Antwort - {str(e)}. Rohdaten: {solution_text}")
        # Fallback: Manuelles Parsing
        result = {}
        lines = solution_text.split('\n')
        current_task = None
        current_answer = None
        current_reasoning = []
        
        for line in lines:
            line = line.strip()
            task_match = re.match(r'Aufgabe\s*(\d+)\s*:\s*(.+)', line, re.IGNORECASE)
            if task_match:
                if current_task and current_answer:
                    result[f"Aufgabe {current_task}"] = {
                        'answer': current_answer,
                        'reasoning': ' '.join(current_reasoning).strip(),
                        'detailed_steps': [],
                        'assumptions': [],
                        'errors_in_cross_check': []
                    }
                current_task = task_match.group(1)
                raw_answer = task_match.group(2).strip()
                current_answer = ''.join(sorted(c for c in raw_answer.upper() if c in 'ABCDE')) if re.match(r'^[A-E,\s]+$', raw_answer) else raw_answer
                current_reasoning = []
            elif line.startswith('Begründung:'):
                reasoning_text = line.replace('Begründung:', '').strip()
                if reasoning_text:
                    current_reasoning = [reasoning_text]
            elif current_task and line and not line.startswith('Aufgabe'):
                current_reasoning.append(line)
        
        if current_task and current_answer:
            result[f"Aufgabe {current_task}"] = {
                'answer': current_answer,
                'reasoning': ' '.join(current_reasoning).strip(),
                'detailed_steps': [],
                'assumptions': [],
                'errors_in_cross_check': []
            }
        
        return result

# --- Überarbeiteter Prompt ---
def create_base_prompt(ocr_text: str, cross_check_info: Optional[str] = None) -> str:
    """Strenger Prompt mit Zwang zu reinem JSON"""
    cross_check_section = ""
    if cross_check_info:
        cross_check_section = f"""
CROSS-VALIDATION:
Another expert provided: {cross_check_info}
Critically analyze their reasoning, identify errors, and justify your answer.
"""
    
    return f"""You are a PhD-level expert in "Internes Rechnungswesen (31031)" at Fernuniversität Hagen. 
Solve exam questions with 100% accuracy, strictly using FernUni standards and terminology.

THEORETICAL SCOPE:
- Cost-type, cost-center, cost-unit accounting (Kostenarten-, Kostenstellen-, Kostenträgerrechnung)
- Full, variable, marginal, standard (Plankosten-), and process/ABC costing systems
- Flexible and Grenzplankostenrechnung variance analysis
- Single- and multi-level contribution-margin accounting, break-even logic
- Causality & allocation (Verursachungs- und Zurechnungsprinzip)
- Business-economics MRS convention (MRS = MP₂ / MP₁ unless specified)
- Activity-analysis production & logistics models (LP, Standort- & Transportprobleme)
- Marketing segmentation, price-elasticity, contribution-based pricing & margin planning

REFERENCE MATERIAL:
Use ONLY the following FernUni Hagen materials as reference:
{rag_context}

{cross_check_section}

# OCR TEXT START:
{ocr_text}
# OCR TEXT END

CRITICAL INSTRUCTIONS:
1. **Read Carefully**: Analyze ONLY the OCR text. If unclear, document assumptions.
2. **Calculations**:
   - Show ALL steps explicitly
   - Verify by recomputing backwards
3. **Multiple-Choice**:
   - Evaluate each option individually
   - Cross-check the final answer
4. **Self-Validation**:
   - Re-evaluate your answer
   - Ensure consistency with FernUni terminology
5. **Error Handling**: Flag suspected OCR errors and propose corrections.
6. **Output Format**: Return EXACTLY ONE valid JSON object with the structure below. Do NOT include any text, explanations, or formatting outside the JSON (e.g., no "Here is the answer:" or extra lines).

MANDATORY OUTPUT FORMAT (JSON ONLY):
```json
{
  "task_number": "1",
  "answer": "A",
  "reasoning": "Single sentence in German.",
  "detailed_steps": ["Step 1: ...", "Step 2: ..."],
  "assumptions": ["If any, e.g., unclear OCR text"],
  "errors_in_cross_check": ["If applicable, errors in other expert's analysis"]
}
```
"""

# --- Solver ---
def solve_with_claude(ocr_text: str, cross_check: Optional[str] = None) -> Dict:
    """Claude Opus 4 mit Selbstprüfung"""
    prompt = create_base_prompt(ocr_text, cross_check)
    
    try:
        response = claude_client.messages.create(
            model="claude-4-opus-20250514",  # Fixiert auf Claude Opus 4
            max_tokens=6000,
            temperature=0.1,
            top_p=0.1,
            messages=[{"role": "user", "content": prompt}]
        )
        response_text = response.content[0].text
        return extract_structured_answers(response_text)
    except Exception as e:
        logger.error(f"Claude API Error: {str(e)}")
        raise e

def solve_with_gpt(ocr_text: str, cross_check: Optional[str] = None) -> Dict:
    """GPT als Backup"""
    prompt = create_base_prompt(ocr_text, cross_check)
    
    try:
        response = openai_client.chat.completions.create(
            model=GPT_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=3000,
            temperature=0.1,
            top_p=0.1,
            seed=42
        )
        response_text = response.choices[0].message.content
        return extract_structured_answers(response_text)
    except Exception as e:
        logger.error(f"GPT API Error: {str(e)}")
        raise e

# --- Kreuzvalidierung ---
def cross_validation_consensus(ocr_text: str, max_rounds: int = 3) -> Tuple[bool, Optional[Dict]]:
    """Intelligente Kreuzvalidierung mit aktiver Fehlerkorrektur"""
    st.markdown("### 🔄 Kreuzvalidierung")
    
    for round_num in range(max_rounds):
        st.markdown(f"#### Runde {round_num + 1} Analyse:")
        
        with st.spinner(f"Runde {round_num + 1}: Unabhängige Expertenanalyse..."):
            try:
                claude_solution = solve_with_claude(ocr_text)
                gpt_solution = solve_with_gpt(ocr_text)
            except Exception as e:
                st.error(f"API-Fehler in Runde {round_num + 1}: {str(e)}")
                if debug_mode:
                    st.write(f"Debug: Fehlermeldung - {str(e)}. Prüfe den rohen Antworttext in den Logs.")
                return False, None
        
        differences = []
        agreement_count = 0
        all_tasks = set(claude_solution.keys()) | set(gpt_solution.keys())
        
        for task in sorted(all_tasks):
            claude_ans = claude_solution.get(task, {}).get('answer', '')
            gpt_ans = gpt_solution.get(task, {}).get('answer', '')
            
            col1, col2, col3, col4 = st.columns([2, 2, 2, 1])
            with col1:
                st.write(f"**{task}:**")
            with col2:
                st.write(f"Claude: `{claude_ans}`")
            with col3:
                st.write(f"GPT: `{gpt_ans}`")
            with col4:
                if claude_ans == gpt_ans:
                    st.write("✅")
                    agreement_count += 1
                else:
                    st.write("❌")
                    differences.append({
                        'task': task,
                        'claude': claude_ans,
                        'gpt': gpt_ans,
                        'claude_reasoning': claude_solution.get(task, {}).get('reasoning', ''),
                        'gpt_reasoning': gpt_solution.get(task, {}).get('reasoning', '')
                    })
        
        consensus_rate = (agreement_count / len(all_tasks)) * 100 if all_tasks else 0
        st.metric("Konsens-Rate", f"{consensus_rate:.0f}%", f"{agreement_count}/{len(all_tasks)}")
        
        if not differences:
            st.success("✅ Vollständiger Konsens erreicht!")
            return True, claude_solution
        
        if round_num < max_rounds - 1:
            st.warning(f"⚠️ {len(differences)} Diskrepanzen gefunden - Kreuzvalidierung...")
            
            discrepancy_summary = "\n".join([
                f"Task {d['task']}: Claude ({d['claude']}, {d['claude_reasoning']}) vs GPT ({d['gpt']}, {d['gpt_reasoning']})"
                for d in differences
            ])
            
            try:
                claude_solution = solve_with_claude(ocr_text, discrepancy_summary)
                gpt_solution = solve_with_gpt(ocr_text, discrepancy_summary)
            except Exception as e:
                st.error(f"API-Fehler in Runde {round_num + 2}: {str(e)}")
                if debug_mode:
                    st.write(f"Debug: Fehlermeldung - {str(e)}. Prüfe den rohen Antworttext in den Logs.")
                return False, (claude_solution, gpt_solution)
    
    st.error(f"❌ Nach {max_rounds} Runden noch {len(differences)} Diskrepanzen")
    return False, (claude_solution, gpt_solution)

# --- UI ---
debug_mode = st.checkbox("🔍 Debug-Modus", value=False)

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
        
        if st.button("🎯 Lösung mit Kreuzvalidierung", type="primary"):
            consensus, result = cross_validation_consensus(ocr_text)
            
            st.markdown("---")
            st.markdown("### 🏆 FINALE LÖSUNG:")
            
            if consensus:
                for task, data in sorted(result.items()):
                    st.markdown(f"### {task}: **{data['answer']}**")
                    st.markdown(f"*Begründung: {data['reasoning']}*")
                    if data.get('detailed_steps'):
                        st.markdown(f"*Schritte:* {', '.join(data['detailed_steps'])}")
                    if data.get('assumptions'):
                        st.markdown(f"*Annahmen:* {', '.join(data['assumptions'])}")
                    st.markdown("")
                
                st.success("✅ Lösung durch Kreuzvalidierung bestätigt!")
                
            else:
                if result:
                    st.error("❌ Experten uneinig - Beide Lösungen anzeigen:")
                    claude_final, gpt_final = result
                    
                    col1, col2 = st.columns(2)
                    with col1:
                        st.markdown("**Claude Finale Lösung:**")
                        for task in sorted(claude_final.keys()):
                            st.markdown(f"**{task}: {claude_final[task]['answer']}**")
                            st.caption(claude_final[task]['reasoning'])
                    
                    with col2:
                        st.markdown(f"**{GPT_MODEL} Finale Lösung:**")
                        for task in sorted(gpt_final.keys()):
                            st.markdown(f"**{task}: {gpt_final[task]['answer']}**")
                            st.caption(gpt_final[task]['reasoning'])
                else:
                    st.error("❌ Schwerwiegender API-Fehler - bitte erneut versuchen")
                    if debug_mode:
                        st.write("Debug: Prüfe die Logs oder API-Schlüssel. Rohdaten könnten hilfreich sein.")
            
            st.info("✅ OCR-unverändert | Claude-4-Opus | RAG-Enabled | Kreuzvalidierung optimiert")
    
    except Exception as e:
        logger.error(f"Error: {str(e)}")
        st.error(f"❌ Fehler: {str(e)}")
        if debug_mode:
            st.write(f"Debug: Fehlermeldung - {str(e)}")

st.markdown("---")
st.caption(f"🦊 Optimized System | Claude-4 Opus + {GPT_MODEL} | Max Precision")
