"""Dashboard didático de monitoramento elétrico (simulação e ESP32 via HTTP)."""
import math
import random
import time
from datetime import datetime

import pandas as pd
import requests
import streamlit as st

st.set_page_config(page_title="Energia Inteligente", page_icon="⚡", layout="wide")

EQUIPAMENTOS = {
    "Lâmpada LED": 12,
    "Ventilador": 70,
    "Notebook": 65,
    "Computador": 180,
    "Geladeira (estimativa instantânea)": 140,
}

if "historico" not in st.session_state:
    st.session_state.historico = []
if "energia_kwh" not in st.session_state:
    st.session_state.energia_kwh = 0.0
if "inicio" not in st.session_state:
    st.session_state.inicio = time.monotonic()
if "ultima_amostra" not in st.session_state:
    st.session_state.ultima_amostra = time.monotonic()
if "em_execucao" not in st.session_state:
    st.session_state.em_execucao = True
if "amostra" not in st.session_state:
    st.session_state.amostra = None
if "ultima_config" not in st.session_state:
    st.session_state.ultima_config = None

st.title("⚡ Energia Inteligente")
st.caption("Projeto de extensão • Monitoramento de energia elétrica • Protótipo de software")

with st.sidebar:
    st.header("Configurações")
    modo = st.radio("Fonte dos dados", ["Simulação", "ESP32 (Wi-Fi)"], index=0)
    equipamento = st.selectbox("Equipamento simulado", list(EQUIPAMENTOS)) if modo == "Simulação" else None
    endereco = st.text_input("Endereço do ESP32", "http://192.168.1.100/dados") if modo != "Simulação" else ""
    tarifa = st.number_input("Tarifa (R$/kWh)", min_value=0.0, value=0.90, step=0.05, format="%.2f")
    col_play, col_reset = st.columns(2)
    with col_play:
        if st.button("⏸ Pausar" if st.session_state.em_execucao else "▶ Retomar", use_container_width=True):
            st.session_state.em_execucao = not st.session_state.em_execucao
            st.session_state.ultima_amostra = time.monotonic()
    with col_reset:
        if st.button("↻ Zerar", use_container_width=True):
            st.session_state.historico = []
            st.session_state.energia_kwh = 0.0
            st.session_state.inicio = time.monotonic()
            st.session_state.ultima_amostra = time.monotonic()
            st.session_state.amostra = None
    st.caption("Os dados desta versão ficam apenas na sessão do navegador e não são salvos em banco de dados.")

config = (modo, equipamento, endereco)
if config != st.session_state.ultima_config:
    st.session_state.ultima_config = config
    st.session_state.ultima_amostra = time.monotonic()
    st.session_state.historico = []
    st.session_state.energia_kwh = 0.0
    st.session_state.inicio = time.monotonic()
    st.session_state.amostra = None


def obter_leitura_simulada(nome):
    potencia_base = EQUIPAMENTOS[nome]
    tensao = random.uniform(217, 223)
    potencia = max(0.0, potencia_base * random.uniform(0.89, 1.11))
    corrente = potencia / tensao  # Modelo simplificado: fator de potência = 1
    return {"tensao": tensao, "corrente": corrente, "potencia": potencia}


def obter_leitura_esp32(url):
    """O ESP32 deverá responder JSON: {"tensao": 220, "corrente": 0.5, "potencia": 110}."""
    resposta = requests.get(url, timeout=1.5)
    resposta.raise_for_status()
    dados = resposta.json()
    leitura = {chave: float(dados[chave]) for chave in ("tensao", "corrente", "potencia")}
    if any(not math.isfinite(v) for v in leitura.values()):
        raise ValueError("Leitura inválida do ESP32: valor não numérico ou infinito")
    if leitura["tensao"] <= 0 or any(v < 0 for v in leitura.values()):
        raise ValueError("Leitura inválida do ESP32: tensão deve ser positiva e corrente/potência não podem ser negativas")
    return leitura


@st.fragment(run_every="2s")
def painel():
    ativo = st.session_state.em_execucao
    agora = time.monotonic()
    conectado = False
    erro = ""

    if ativo:
        if modo == "Simulação":
            leitura = obter_leitura_simulada(equipamento)
            conectado = False  # SIMULADO não é ESP32 conectado
        else:
            try:
                leitura = obter_leitura_esp32(endereco)
                conectado = True
            except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
                erro = str(exc)
                leitura = None
        if leitura is not None:
            delta_horas = max(0.0, agora - st.session_state.ultima_amostra) / 3600
            st.session_state.energia_kwh += leitura["potencia"] / 1000 * delta_horas
            st.session_state.amostra = leitura
            st.session_state.historico.append({"Horário": datetime.now(), "Potência (W)": leitura["potencia"]})
            st.session_state.historico = st.session_state.historico[-60:]
        st.session_state.ultima_amostra = agora

    if modo == "Simulação":
        st.info("🧪 MODO SIMULAÇÃO — leituras fictícias para demonstrar o software; ESP32 não conectado.")
    elif conectado:
        st.success("🟢 ESP32 conectado — recebendo dados via Wi-Fi")
    elif not ativo:
        st.warning("⏸ Monitoramento pausado — conexão não verificada")
    else:
        st.error("🔴 ESP32 desconectado ou sem resposta")
        st.caption(f"Detalhe da conexão: {erro}")

    leitura = st.session_state.amostra
    if leitura is None:
        leitura = {"tensao": 0.0, "corrente": 0.0, "potencia": 0.0}

    a, b, c, d = st.columns(4)
    a.metric("Tensão", f"{leitura['tensao']:.1f} V")
    b.metric("Corrente", f"{leitura['corrente']:.3f} A")
    c.metric("Potência", f"{leitura['potencia']:.1f} W")
    d.metric("Energia estimada", f"{st.session_state.energia_kwh:.5f} kWh")

    st.subheader("Variação da potência")
    if st.session_state.historico:
        dados = pd.DataFrame(st.session_state.historico)
        st.line_chart(dados.set_index("Horário")["Potência (W)"], height=300)
    else:
        st.caption("O gráfico aparecerá quando houver leituras.")

    tempo = int(max(0, agora - st.session_state.inicio))
    h, resto = divmod(tempo, 3600)
    m, s = divmod(resto, 60)
    e, f = st.columns(2)
    e.metric("Tempo desde o início/reset", f"{h:02d}:{m:02d}:{s:02d}")
    f.metric("Custo estimado", f"R$ {st.session_state.energia_kwh * tarifa:.4f}")
    st.caption("Cálculo: energia (kWh) = soma de potência (kW) × intervalo (h). Custo = energia × tarifa. Estimativas didáticas, não medições homologadas.")


painel()
