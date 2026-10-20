"""Painel local Streamlit para consultar catálogo e histórico reais."""
import json
from pathlib import Path
import sys
import subprocess

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src.engine.execution_history import ExecutionHistory

st.set_page_config(page_title="Observatório de Diadema", layout="wide")
st.title("Monitoramento da coleta de dados")
catalog_path = ROOT / "data/raw/catalogo_geral.json"
catalog = json.loads(catalog_path.read_text(encoding="utf-8")) if catalog_path.exists() else []
history = ExecutionHistory(ROOT / "data/history").get_records()
df = pd.DataFrame(catalog)
if df.empty:
    st.info("O catálogo ainda não possui fontes.")
else:
    c1, c2, c3 = st.columns(3)
    c1.metric("Fontes cadastradas", len(df))
    c2.metric("Sucesso no último catálogo", int(df.status.astype(str).eq("SUCESSO").sum()))
    c3.metric("Falhas registradas", int(df.status.astype(str).str.startswith("FALHA").sum()))
    tipos = ["Todos", *sorted(df.tipo_fonte.dropna().unique())]
    tipo = st.selectbox("Tipo de fonte", tipos)
    status = st.selectbox("Status", ["Todos", *sorted(df.status.dropna().unique())])
    view = df.copy()
    if tipo != "Todos": view = view[view.tipo_fonte == tipo]
    if status != "Todos": view = view[view.status == status]
    st.dataframe(view, use_container_width=True, hide_index=True)
st.subheader("Histórico de execuções")
if history:
    st.dataframe(pd.DataFrame(history).sort_values("id", ascending=False), use_container_width=True, hide_index=True)
else:
    st.caption("Nenhuma execução registrada no SQLite ainda.")

st.subheader("Cards Metabase")
mb_path = ROOT / "data/raw/metabase/catalogo_metabase.json"
cards = json.loads(mb_path.read_text(encoding="utf-8")) if mb_path.exists() else []
frequency_path = ROOT / "config/metabase_cards.json"
frequencies = json.loads(frequency_path.read_text(encoding="utf-8")).get("cards", {}) if frequency_path.exists() else {}
hist_obj = ExecutionHistory(ROOT / "data/history")
for card in cards:
    key = f"{card.get('dashboard_uuid')}:{card.get('card_id')}"
    hist_obj.set_frequency(key, "metabase", frequencies.get(key, {}).get("frequencia", "manual"))
schedule_state = {row["fonte_id"]: row for row in hist_obj.get_schedule_states()}
latest = {}
for row in history:
    if row.get("fonte_tipo") == "metabase":
        latest[row["fonte_id"]] = row
card_rows = []
for card in cards:
    key = f"{card.get('dashboard_uuid')}:{card.get('card_id')}"
    state = schedule_state.get(key, {})
    freq = frequencies.get(key, {}).get("frequencia", state.get("frequencia", "manual"))
    due, last_success, next_run = hist_obj.is_due_for_update(key, freq)
    attempt = latest.get(key)
    status = "com falha" if attempt and str(attempt.get("status", "")).startswith("FALHA") else ("vencido" if due else ("atualizado" if last_success else "sem histórico"))
    card_rows.append({"card": key, "nome": card.get("card_name"), "frequência": freq,
                      "status": status, "última tentativa": state.get("ultima_tentativa_utc") or (attempt.get("data_fim_utc") if attempt else None),
                      "último sucesso": state.get("ultima_atualizacao_sucesso_utc") or (last_success.get("data_fim_utc") if last_success else None),
                      "próxima atualização": state.get("proxima_execucao_utc") or (next_run.isoformat() if next_run else None)})
if card_rows:
    cards_df = pd.DataFrame(card_rows)
    mc1, mc2, mc3 = st.columns(3)
    mc1.metric("Cards vencidos", int(cards_df.status.eq("vencido").sum()))
    mc2.metric("Cards atualizados", int(cards_df.status.eq("atualizado").sum()))
    mc3.metric("Cards com falha", int(cards_df.status.eq("com falha").sum()))
    st.dataframe(cards_df, use_container_width=True, hide_index=True)
    selected_card = st.selectbox("Histórico do card", sorted(cards_df.card.tolist()))
    selected_history = [r for r in history if r.get("fonte_tipo") == "metabase" and r.get("fonte_id") == selected_card]
    if selected_history:
        st.dataframe(pd.DataFrame(selected_history).sort_values("id", ascending=False), use_container_width=True, hide_index=True)
    else:
        st.caption("Este card ainda não tem tentativas no histórico SQLite.")
else:
    st.info("Catálogo Metabase não encontrado.")

st.subheader("Agendador do Windows")
if sys.platform == "win32":
    query = subprocess.run([sys.executable, str(ROOT / "scripts/agendamento_windows.py"), "query"], cwd=ROOT, capture_output=True, text=True)
    if query.returncode == 0:
        st.success("Tarefa encontrada no Agendador do Windows.")
        st.code(query.stdout)
    else:
        st.info("Tarefa não configurada ou não consultável. Para instalar: `py scripts/agendamento_windows.py install --frequency weekly --time 06:00`.")
else:
    st.info("O estado do Agendador só pode ser confirmado no Windows. Nenhuma tarefa será presumida ativa.")
with st.form("coleta_manual"):
    confirm = st.checkbox("Confirmo iniciar uma coleta de todas as fontes públicas configuradas.")
    submitted = st.form_submit_button("Iniciar coleta", type="primary")
if submitted:
    if not confirm:
        st.error("Marque a confirmação para iniciar a coleta.")
    else:
        proc = subprocess.run([sys.executable, str(ROOT / "scripts/coletar_dados.py")], cwd=ROOT, capture_output=True, text=True)
        st.code(proc.stdout or proc.stderr)
        st.success("Coleta finalizada." if proc.returncode == 0 else f"Coleta terminou com código {proc.returncode}.")
