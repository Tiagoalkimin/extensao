"""Dashboard didático de monitoramento elétrico (simulação e ESP32 via HTTP)."""

from datetime import datetime
import math
import random
import time

import pandas as pd
import plotly.express as px
import requests
import streamlit as st
from streamlit_autorefresh import st_autorefresh


# ---------------------------------------------------------------------
# Configuração da página e visual
# ---------------------------------------------------------------------
st.set_page_config(
    page_title="Energia Inteligente",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    .stApp {
        background: linear-gradient(145deg, #0b1220 0%, #101b2d 55%, #0b1422 100%);
        color: #edf3fb;
    }
    [data-testid="stSidebar"] {
        background: #101a2b;
        border-right: 1px solid rgba(148, 163, 184, .16);
    }
    [data-testid="stMetric"] {
        background: rgba(24, 39, 61, .88);
        border: 1px solid rgba(148, 163, 184, .18);
        padding: 16px 18px;
        border-radius: 14px;
        box-shadow: 0 8px 24px rgba(0,0,0,.14);
    }
    [data-testid="stMetricLabel"] {
        color: #a9bad0;
    }
    [data-testid="stMetricValue"] {
        color: #f4f8ff;
    }
    .hero {
        padding: 22px 26px;
        border-radius: 18px;
        background: linear-gradient(105deg, rgba(14,165,233,.18), rgba(16,185,129,.10));
        border: 1px solid rgba(56,189,248,.22);
        margin-bottom: 18px;
    }
    .hero h1 {
        margin: 0;
        color: #f4f8ff;
        font-size: 2rem;
        letter-spacing: -.7px;
    }
    .hero p {
        color: #b7c7da;
        margin: 7px 0 0 0;
    }
    .section-title {
        color: #e7effa;
        font-size: 1.12rem;
        font-weight: 650;
        margin: 12px 0 8px 0;
    }
    .small-note {
        color: #9fb0c5;
        font-size: .82rem;
    }
    div.stButton > button {
        border-radius: 10px;
        border: 1px solid rgba(148,163,184,.25);
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------
# Estado da sessão
# ---------------------------------------------------------------------
DEFAULTS = {
    "historico": [],
    "energia_sessao": 0.0,
    "ultima_energia_sensor": None,
    "ultima_chave_leitura": None,
    "ultima_leitura": None,
    "ultimo_recebimento": None,
    "inicio": time.monotonic(),
    "em_execucao": True,
    "erro_api": "",
    "contador_simulado": 0,
}
for chave, valor in DEFAULTS.items():
    if chave not in st.session_state:
        st.session_state[chave] = valor


# ---------------------------------------------------------------------
# Equipamentos da simulação
# ---------------------------------------------------------------------
EQUIPAMENTOS = {
    "Lâmpada LED": 12,
    "Ventilador": 70,
    "Notebook": 65,
    "Computador": 180,
    "Geladeira (estimativa instantânea)": 140,
}


def reiniciar_sessao():
    """Zera somente as estatísticas desta sessão do dashboard."""
    st.session_state.historico = []
    st.session_state.energia_sessao = 0.0
    st.session_state.ultima_energia_sensor = None
    st.session_state.ultima_chave_leitura = None
    st.session_state.ultima_leitura = None
    st.session_state.ultimo_recebimento = None
    st.session_state.inicio = time.monotonic()
    st.session_state.erro_api = ""


def numero_valido(valor, nome, minimo=None):
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        raise ValueError(f"O campo '{nome}' não é numérico.")
    if not math.isfinite(numero):
        raise ValueError(f"O campo '{nome}' contém um valor inválido.")
    if minimo is not None and numero < minimo:
        raise ValueError(f"O campo '{nome}' não pode ser menor que {minimo}.")
    return numero


def normalizar_resposta(payload):
    """Aceita o JSON direto ou encapsulado em dados/medicao/ultima."""
    if not isinstance(payload, dict):
        raise ValueError("A API não retornou um objeto JSON.")

    for chave in ("dados", "medicao", "ultima", "data"):
        if isinstance(payload.get(chave), dict):
            payload = payload[chave]
            break

    leitura = {
        "tensao": numero_valido(payload.get("tensao"), "tensao", 0),
        "corrente": numero_valido(payload.get("corrente"), "corrente", 0),
        "potencia": numero_valido(payload.get("potencia"), "potencia", 0),
    }

    # Estes campos são opcionais para manter compatibilidade com versões
    # iniciais do firmware/servidor.
    for campo in ("energia", "frequencia", "fator_potencia"):
        valor = payload.get(campo)
        leitura[campo] = (
            numero_valido(valor, campo, 0) if valor is not None else None
        )

    leitura["timestamp"] = payload.get("timestamp") or payload.get("horario")
    leitura["energia_sessao_api"] = payload.get("energia_sessao")
    return leitura


def obter_leitura_api(url):
    resposta = requests.get(url, timeout=2.5)
    resposta.raise_for_status()
    return normalizar_resposta(resposta.json())


def obter_leitura_simulada(equipamento):
    base = EQUIPAMENTOS[equipamento]
    tensao = random.uniform(218, 222)
    potencia = max(0.0, base * random.uniform(0.88, 1.12))
    fator = random.uniform(0.90, 0.99)
    corrente = potencia / (tensao * fator) if tensao else 0.0

    st.session_state.contador_simulado += 1
    energia = st.session_state.energia_sessao + potencia / 1000 * 2 / 3600

    return {
        "tensao": tensao,
        "corrente": corrente,
        "potencia": potencia,
        "energia": energia,
        "frequencia": random.uniform(59.9, 60.1),
        "fator_potencia": fator,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "energia_sessao_api": None,
    }


def registrar_leitura(leitura):
    """Atualiza energia, histórico e última leitura sem duplicar amostras."""
    timestamp = leitura.get("timestamp")
    chave = timestamp or tuple(
        round(leitura.get(campo) or 0, 4)
        for campo in ("tensao", "corrente", "potencia", "energia")
    )

    if chave == st.session_state.ultima_chave_leitura:
        # A API pode devolver a mesma última amostra em várias consultas.
        st.session_state.ultimo_recebimento = time.monotonic()
        st.session_state.ultima_leitura = leitura
        return

    energia_api = leitura.get("energia_sessao_api")
    energia_sensor = leitura.get("energia")

    if energia_api is not None:
        st.session_state.energia_sessao = numero_valido(
            energia_api, "energia_sessao", 0
        )
    elif energia_sensor is not None:
        anterior = st.session_state.ultima_energia_sensor
        if anterior is not None:
            # Se o contador do medidor reiniciar, considera a nova leitura
            # como energia acumulada desde o reinício.
            incremento = (
                energia_sensor - anterior
                if energia_sensor >= anterior
                else energia_sensor
            )
            st.session_state.energia_sessao += max(0.0, incremento)
        st.session_state.ultima_energia_sensor = energia_sensor

    st.session_state.ultima_chave_leitura = chave
    st.session_state.ultima_leitura = leitura
    st.session_state.ultimo_recebimento = time.monotonic()

    horario = datetime.now()
    if timestamp:
        try:
            horario = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            pass

    st.session_state.historico.append(
        {
            "Horário": horario,
            "Potência (W)": leitura["potencia"],
            "Energia da sessão (kWh)": st.session_state.energia_sessao,
        }
    )
    st.session_state.historico = st.session_state.historico[-300:]


# ---------------------------------------------------------------------
# Barra lateral
# ---------------------------------------------------------------------
with st.sidebar:
    st.markdown("## ⚙️ Configurações")
    modo = st.radio(
        "Origem das medições",
        ["Simulação", "Servidor FastAPI"],
        index=0,
    )

    equipamento = None
    if modo == "Simulação":
        equipamento = st.selectbox(
            "Equipamento demonstrativo", list(EQUIPAMENTOS.keys())
        )
    else:
        url_api = st.text_input(
            "URL da última medição",
            "http://127.0.0.1:8000/api/atual",
            help="Use o endereço do computador onde o FastAPI está executando.",
        )

    tarifa = st.number_input(
        "Tarifa de energia (R$/kWh)",
        min_value=0.0,
        value=0.90,
        step=0.05,
        format="%.2f",
    )
    limite_potencia = st.number_input(
        "Alerta de potência (W)",
        min_value=1,
        value=1000,
        step=100,
    )

    st.divider()
    c1, c2 = st.columns(2)
    with c1:
        if st.button(
            "⏸ Pausar" if st.session_state.em_execucao else "▶ Retomar",
            use_container_width=True,
        ):
            st.session_state.em_execucao = not st.session_state.em_execucao
    with c2:
        if st.button("↻ Zerar", use_container_width=True):
            reiniciar_sessao()

    st.divider()
    st.caption("Atualização automática: a cada 2 segundos.")
    st.caption("Histórico temporário: últimas 300 amostras.")
    st.caption("Os dados são mantidos em memória durante a sessão.")


# ---------------------------------------------------------------------
# Cabeçalho
# ---------------------------------------------------------------------
st.markdown(
    """
    <div class="hero">
        <h1>⚡ Energia Inteligente</h1>
        <p>Monitoramento elétrico em tempo real • Eficiência energética • IoT</p>
    </div>
    """,
    unsafe_allow_html=True,
)

# Atualização periódica da interface
st_autorefresh(interval=2000, key="atualizacao_dashboard")


# ---------------------------------------------------------------------
# Leitura de dados
# ---------------------------------------------------------------------
erro = ""
conectado = False

if st.session_state.em_execucao:
    if modo == "Simulação":
        leitura_nova = obter_leitura_simulada(equipamento)
        registrar_leitura(leitura_nova)
        conectado = True
    else:
        try:
            leitura_nova = obter_leitura_api(url_api)
            registrar_leitura(leitura_nova)
            conectado = True
            st.session_state.erro_api = ""
        except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
            erro = str(exc)
            st.session_state.erro_api = erro

leitura = st.session_state.ultima_leitura

# ---------------------------------------------------------------------
# Status da conexão e alertas
# ---------------------------------------------------------------------
status_col, hora_col = st.columns([2, 1])

with status_col:
    if not st.session_state.em_execucao:
        st.warning("⏸ Monitoramento pausado")
    elif modo == "Simulação":
        st.info("🧪 Modo demonstração — os valores exibidos são simulados")
    elif conectado:
        st.success("🟢 Servidor FastAPI respondendo — última medição recebida")
    else:
        st.error("🔴 Sem comunicação com o servidor FastAPI")
        if erro:
            st.caption(f"Detalhe: {erro}")

with hora_col:
    if st.session_state.ultimo_recebimento:
        segundos = int(time.monotonic() - st.session_state.ultimo_recebimento)
        st.caption(f"Última resposta recebida há {segundos} s")

if leitura and leitura["potencia"] >= limite_potencia:
    st.warning(
        f"⚠️ Potência acima do limite configurado: "
        f"{leitura['potencia']:.1f} W (limite: {limite_potencia} W)"
    )

if leitura is None:
    st.info("Aguardando a primeira medição...")
    st.stop()


# ---------------------------------------------------------------------
# Indicadores principais
# ---------------------------------------------------------------------
st.markdown('<div class="section-title">Indicadores elétricos</div>', unsafe_allow_html=True)

k1, k2, k3, k4 = st.columns(4)
k1.metric("⚡ Potência", f"{leitura['potencia']:.1f} W")
k2.metric("🔌 Tensão", f"{leitura['tensao']:.1f} V")
k3.metric("〰️ Corrente", f"{leitura['corrente']:.3f} A")
k4.metric("📊 Energia da sessão", f"{st.session_state.energia_sessao:.5f} kWh")

k5, k6, k7 = st.columns(3)
frequencia = leitura.get("frequencia")
fator_potencia = leitura.get("fator_potencia")
k5.metric("Frequência", f"{frequencia:.2f} Hz" if frequencia is not None else "—")
k6.metric(
    "Fator de potência",
    f"{fator_potencia:.2f}" if fator_potencia is not None else "—",
)
k7.metric(
    "Custo estimado",
    f"R$ {st.session_state.energia_sessao * tarifa:.4f}",
)


# ---------------------------------------------------------------------
# Gráficos
# ---------------------------------------------------------------------
st.markdown('<div class="section-title">Histórico de consumo</div>', unsafe_allow_html=True)

if st.session_state.historico:
    df = pd.DataFrame(st.session_state.historico)
    graf1, graf2 = st.columns(2)

    with graf1:
        fig_potencia = px.line(
            df,
            x="Horário",
            y="Potência (W)",
            title="Potência instantânea",
            markers=True,
        )
        fig_potencia.update_traces(line=dict(width=3), marker=dict(size=5))
        fig_potencia.update_layout(
            template="plotly_dark",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(18,31,49,.55)",
            margin=dict(l=10, r=10, t=55, b=10),
            height=330,
            xaxis_title="Horário",
            yaxis_title="Potência (W)",
        )
        st.plotly_chart(fig_potencia, use_container_width=True)

    with graf2:
        fig_energia = px.area(
            df,
            x="Horário",
            y="Energia da sessão (kWh)",
            title="Energia acumulada na sessão",
        )
        fig_energia.update_traces(line=dict(width=3))
        fig_energia.update_layout(
            template="plotly_dark",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(18,31,49,.55)",
            margin=dict(l=10, r=10, t=55, b=10),
            height=330,
            xaxis_title="Horário",
            yaxis_title="Energia (kWh)",
        )
        st.plotly_chart(fig_energia, use_container_width=True)
else:
    st.caption("Os gráficos serão preenchidos assim que chegarem medições válidas.")


# ---------------------------------------------------------------------
# Resumo da sessão e observações
# ---------------------------------------------------------------------
tempo = int(max(0, time.monotonic() - st.session_state.inicio))
horas, resto = divmod(tempo, 3600)
minutos, segundos = divmod(resto, 60)

st.markdown('<div class="section-title">Resumo do monitoramento</div>', unsafe_allow_html=True)
r1, r2, r3 = st.columns(3)
r1.metric("Tempo desde o início/reset", f"{horas:02d}:{minutos:02d}:{segundos:02d}")
r2.metric("Custo estimado", f"R$ {st.session_state.energia_sessao * tarifa:.4f}")
r3.metric("Amostras no histórico", str(len(st.session_state.historico)))

st.markdown(
    """
    <p class="small-note">
    Energia da sessão calculada a partir do contador acumulado do PZEM-004T
    (quando disponível). Se o servidor enviar <code>energia_sessao</code>,
    esse valor será priorizado. O histórico permanece em memória e é perdido
    ao encerrar/reiniciar a sessão ou o servidor.
    </p>
    """,
    unsafe_allow_html=True,
)
