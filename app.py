from flask import Flask, render_template, request, redirect, url_for, session, send_file
import os
import psycopg2
from psycopg2.extras import RealDictCursor
import pandas as pd
import unicodedata
from datetime import datetime, date, time, timedelta
from io import BytesIO

app = Flask(__name__)
app.secret_key = "academia_secret"


def conectar():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL nao configurada no ambiente.")

    kwargs = {"cursor_factory": RealDictCursor}

    if "render.com" in database_url and "sslmode=" not in database_url:
        kwargs["sslmode"] = "require"

    return psycopg2.connect(database_url, **kwargs)


def remover_acentos(texto):
    return unicodedata.normalize('NFKD', texto).encode('ASCII', 'ignore').decode('ASCII')


def normalizar_nome(texto):
    return remover_acentos(" ".join(str(texto or "").split())).casefold()


def data_hoje_brasil():
    return (datetime.utcnow() - timedelta(hours=3)).date()


def formatar_data_brasil(valor):
    if not valor:
        return "-"
    if isinstance(valor, datetime):
        return valor.strftime("%d/%m/%Y")
    if isinstance(valor, date):
        return valor.strftime("%d/%m/%Y")

    texto = str(valor)
    if len(texto) >= 10 and texto[4:5] == "-" and texto[7:8] == "-":
        return f"{texto[8:10]}/{texto[5:7]}/{texto[0:4]}"
    return texto


def atualizar_status_vencidos(cursor):
    hoje = data_hoje_brasil().strftime("%Y-%m-%d")
    cursor.execute("""
        UPDATE alunos
        SET status_pagamento = 'Atrasado'
        WHERE vencimento IS NOT NULL
          AND vencimento <> ''
          AND vencimento < %s
          AND status_pagamento <> 'Atrasado'
    """, (hoje,))


def limpar_bloqueios_antigos(cursor):
    hoje = data_hoje_brasil().strftime("%Y-%m-%d")
    cursor.execute("""
        DELETE FROM bloqueios_aulas
        WHERE data_bloqueio < %s
    """, (hoje,))


def normalizar_plano(texto):
    return remover_acentos(" ".join(str(texto or "").split())).upper()


def inteiro_ou_zero(valor):
    try:
        return int(valor or 0)
    except (TypeError, ValueError):
        return 0


def escolher_status_pagamento(alunos):
    prioridade = {"Pago": 3, "Pendente": 2, "Atrasado": 1}
    return max(
        (aluno.get("status_pagamento") or "" for aluno in alunos),
        key=lambda status: prioridade.get(status, 0),
        default=""
    )


def primeiro_valor(alunos, campo):
    for aluno in alunos:
        valor = aluno.get(campo)
        if valor not in (None, ""):
            return valor
    return ""


def texto_ordenavel(valor):
    if valor in (None, ""):
        return ""
    if isinstance(valor, (datetime, date, time)):
        return valor.isoformat()
    return str(valor)


def unir_grupo_alunos_duplicados(cursor, alunos):
    alunos_ordenados = sorted(
        alunos,
        key=lambda aluno: (
            texto_ordenavel(aluno.get("vencimento")),
            1 if aluno.get("aceitou_contrato") else 0,
            aluno.get("id") or 0
        ),
        reverse=True
    )
    principal = alunos_ordenados[0]
    duplicados = alunos_ordenados[1:]
    principal_id = principal["id"]

    aulas_usadas_iniciais = sum(
        inteiro_ou_zero(aluno.get("aulas_usadas_iniciais"))
        for aluno in alunos_ordenados
    )
    aulas_contratadas = inteiro_ou_zero(principal.get("aulas_contratadas")) or max(
        [inteiro_ou_zero(aluno.get("aulas_contratadas")) for aluno in alunos_ordenados],
        default=0
    ) or None
    data_inicio = min(
        [texto_ordenavel(aluno.get("data_inicio")) for aluno in alunos_ordenados if aluno.get("data_inicio")],
        default=""
    )
    vencimento = max(
        [texto_ordenavel(aluno.get("vencimento")) for aluno in alunos_ordenados if aluno.get("vencimento")],
        default=""
    )
    aceitou_contrato = any(aluno.get("aceitou_contrato") for aluno in alunos_ordenados)
    data_aceite_contrato = max(
        [texto_ordenavel(aluno.get("data_aceite_contrato")) for aluno in alunos_ordenados if aluno.get("data_aceite_contrato")],
        default=None
    )

    for duplicado in duplicados:
        duplicado_id = duplicado["id"]
        cursor.execute("""
            UPDATE agendamentos ag
            SET aluno_id = %s
            WHERE ag.aluno_id = %s
              AND NOT EXISTS (
                  SELECT 1
                  FROM agendamentos existente
                  WHERE existente.aluno_id = %s
                    AND existente.aula_id = ag.aula_id
                    AND existente.data_agendamento = ag.data_agendamento
              )
        """, (principal_id, duplicado_id, principal_id))
        cursor.execute("DELETE FROM agendamentos WHERE aluno_id = %s", (duplicado_id,))
        cursor.execute("DELETE FROM alunos WHERE id = %s", (duplicado_id,))

    cursor.execute("""
        UPDATE alunos
        SET telefone = %s,
            vencimento = %s,
            status_pagamento = %s,
            observacao = %s,
            data_nascimento = %s,
            data_inicio = %s,
            aulas_contratadas = %s,
            frequencia = %s,
            aulas_usadas_iniciais = %s,
            aceitou_contrato = %s,
            data_aceite_contrato = %s
        WHERE id = %s
    """, (
        primeiro_valor(alunos_ordenados, "telefone"),
        vencimento,
        escolher_status_pagamento(alunos_ordenados),
        primeiro_valor(alunos_ordenados, "observacao"),
        primeiro_valor(alunos_ordenados, "data_nascimento"),
        data_inicio,
        aulas_contratadas,
        primeiro_valor(alunos_ordenados, "frequencia"),
        aulas_usadas_iniciais,
        aceitou_contrato,
        data_aceite_contrato,
        principal_id
    ))


def unificar_alunos_duplicados(cursor):
    cursor.execute("SELECT * FROM alunos ORDER BY id ASC")
    grupos = {}

    for aluno in cursor.fetchall():
        chave_nome = normalizar_nome(aluno.get("nome"))
        chave_plano = normalizar_plano(aluno.get("plano"))
        if not chave_nome or not chave_plano:
            continue

        grupos.setdefault((chave_nome, chave_plano), []).append(aluno)

    for alunos in grupos.values():
        if len(alunos) > 1:
            unir_grupo_alunos_duplicados(cursor, alunos)


def manutencao_basica_segura(conn, cursor, unificar=True, limpar_bloqueios=False):
    try:
        atualizar_status_vencidos(cursor)
        if unificar:
            unificar_alunos_duplicados(cursor)
        if limpar_bloqueios:
            limpar_bloqueios_antigos(cursor)
        conn.commit()
    except Exception:
        conn.rollback()
        atualizar_status_vencidos(cursor)
        if limpar_bloqueios:
            limpar_bloqueios_antigos(cursor)
        conn.commit()


TABELAS_BACKUP = {
    "alunos": [
        "id", "nome", "telefone", "plano", "vencimento", "status_pagamento",
        "observacao", "aulas_restantes", "usuario", "senha", "data_nascimento",
        "data_inicio", "aulas_contratadas", "aceitou_contrato",
        "data_aceite_contrato", "frequencia", "limite_diario",
        "aulas_usadas_iniciais"
    ],
    "aulas": ["id", "dia_semana", "horario", "modalidade", "capacidade"],
    "agendamentos": ["id", "aluno_id", "aula_id", "data_agendamento"],
    "bloqueios_aulas": [
        "data_bloqueio", "horario_inicio", "horario_fim", "tipo", "motivo"
    ],
}


def valor_backup(valor):
    if pd.isna(valor):
        return None
    if isinstance(valor, pd.Timestamp):
        if valor.time() == datetime.min.time():
            return valor.strftime("%Y-%m-%d")
        return valor.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(valor, datetime):
        return valor.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(valor, date):
        return valor.strftime("%Y-%m-%d")
    if isinstance(valor, time):
        return valor.strftime("%H:%M")
    return valor


def inserir_linhas_backup(cursor, tabela, colunas, linhas):
    colunas_sql = ", ".join(colunas)
    placeholders = ", ".join(["%s"] * len(colunas))

    for _, linha in linhas.iterrows():
        valores = [valor_backup(linha.get(coluna)) for coluna in colunas]
        cursor.execute(
            f"INSERT INTO {tabela} ({colunas_sql}) VALUES ({placeholders})",
            valores
        )


def resetar_sequence(cursor, tabela):
    if tabela not in ("alunos", "aulas", "agendamentos"):
        return

    cursor.execute(f"""
        SELECT setval(
            pg_get_serial_sequence('{tabela}', 'id'),
            COALESCE((SELECT MAX(id) FROM {tabela}), 1),
            (SELECT COUNT(*) > 0 FROM {tabela})
        )
    """)


def limite_plano(plano, aulas_contratadas=None):
    if aulas_contratadas:
        return int(aulas_contratadas)

    plano = remover_acentos(str(plano).upper().strip())

    if plano == "LIGHT":
        return 4
    elif plano == "BASICO":
        return 12
    elif plano in ["CLUBE", "CLUBE+"]:
        return 9999

    return 0


def calcular_aulas_contratadas_auto(data_inicio, data_fim, frequencia):
    if not data_inicio or not data_fim or not frequencia:
        return None

    try:
        inicio = datetime.strptime(str(data_inicio), "%Y-%m-%d").date()
        fim = datetime.strptime(str(data_fim), "%Y-%m-%d").date()
    except Exception:
        return None

    if fim < inicio:
        return None

    dias = (fim - inicio).days + 1
    semanas = dias / 7
    freq = str(frequencia).lower().strip()

    frequencias_semanais = {
        "1x_semana": 1,
        "2x_semana": 2,
        "3x_semana": 3,
        "4x_semana": 4,
        "5x_semana": 5,
    }

    if freq in frequencias_semanais:
        return round(semanas * frequencias_semanais[freq])
    if freq == "1x_dia":
        return dias
    if freq == "2x_dia":
        return dias * 2

    return None


def obter_aulas_contratadas_form(data_inicio, vencimento, frequencia):
    aulas_contratadas = request.form.get("aulas_contratadas") or None

    if not aulas_contratadas:
        aulas_contratadas = calcular_aulas_contratadas_auto(
            data_inicio,
            vencimento,
            frequencia
        )

    return aulas_contratadas


def contar_aulas_usadas(cursor, aluno_id, data_inicio=None):
    if data_inicio:
        cursor.execute("""
            SELECT COUNT(*) AS total
            FROM agendamentos
            WHERE aluno_id = %s AND data_agendamento >= %s
        """, (aluno_id, data_inicio))
    else:
        cursor.execute("""
            SELECT COUNT(*) AS total
            FROM agendamentos
            WHERE aluno_id = %s
        """, (aluno_id,))

    return cursor.fetchone()["total"]


def resumo_aulas_mes(cursor, aluno_id, plano):
    cursor.execute("""
        SELECT aulas_contratadas, aulas_usadas_iniciais, data_inicio
        FROM alunos
        WHERE id = %s
    """, (aluno_id,))

    aluno = cursor.fetchone()
    usadas_sistema = contar_aulas_usadas(cursor, aluno_id, aluno["data_inicio"])

    limite = limite_plano(plano, aluno["aulas_contratadas"])
    usadas = usadas_sistema + (aluno["aulas_usadas_iniciais"] or 0)

    if limite >= 9999:
        return f"{usadas} / ilimitado"

    restantes = max(limite - usadas, 0)
    return f"{usadas} / {limite} usadas - restam {restantes}"


def preencher_resumo_aulas_lista(cursor, alunos):
    if not alunos:
        return

    cursor.execute("SELECT aluno_id, data_agendamento FROM agendamentos")
    agendamentos = cursor.fetchall()

    for aluno in alunos:
        aluno["resumo_aulas"] = montar_resumo_aulas_aluno(aluno, agendamentos)


def montar_resumo_aulas_aluno(aluno, agendamentos):
    aluno_id = aluno["id"]
    data_inicio = texto_ordenavel(aluno.get("data_inicio"))
    usadas_sistema = 0

    for agendamento in agendamentos:
        if agendamento.get("aluno_id") != aluno_id:
            continue

        data_agendamento = texto_ordenavel(agendamento.get("data_agendamento"))
        if data_inicio and data_agendamento < data_inicio:
            continue

        usadas_sistema += 1

    limite = limite_plano(aluno.get("plano"), aluno.get("aulas_contratadas"))
    usadas = usadas_sistema + (aluno.get("aulas_usadas_iniciais") or 0)

    if limite >= 9999:
        return f"{usadas} / ilimitado"

    restantes = max(limite - usadas, 0)
    return f"{usadas} / {limite} usadas - restam {restantes}"


def calcular_idade(data_nascimento):
    if not data_nascimento:
        return None

    try:
        if isinstance(data_nascimento, date):
            nascimento = data_nascimento
        else:
            nascimento = datetime.strptime(str(data_nascimento), "%Y-%m-%d").date()

        hoje = date.today()
        return hoje.year - nascimento.year - ((hoje.month, hoje.day) < (nascimento.month, nascimento.day))
    except Exception:
        return None

def montar_aulas_padrao():
    aulas = []

    def adicionar_musculacao(dia, horas):
        for hora in horas:
            aulas.append((dia, f"{hora:02d}:00", "MUSCULACAO", 10))

    horas_seg_quinta = [5, 6, 7, 8, 9, 10, 15, 16, 17, 18, 19, 20]
    horas_sexta = [5, 6, 7, 8, 9, 10, 15, 16, 17, 18, 19]

    for dia in ["Segunda-feira", "Terca-feira", "Quarta-feira", "Quinta-feira"]:
        adicionar_musculacao(dia, horas_seg_quinta)
    adicionar_musculacao("Sexta-feira", horas_sexta)

    aulas.extend([
        ("Segunda-feira", "07:00", "NEOPILATES", 7),
        ("Segunda-feira", "08:00", "ACROYOGA", 7),
        ("Segunda-feira", "09:00", "NEOPILATES", 7),
        ("Segunda-feira", "16:00", "NEOPILATES", 7),
        ("Segunda-feira", "17:00", "ACROYOGA", 7),
        ("Segunda-feira", "18:00", "NEOPILATES", 7),
        ("Segunda-feira", "18:00", "SPIN FIT", 7),
        ("Segunda-feira", "19:00", "CIRCO", 7),
        ("Segunda-feira", "19:00", "LEG WORK", 7),
        ("Segunda-feira", "20:00", "ACROYOGA", 7),

        ("Terca-feira", "05:00", "NEOPILATES", 7),
        ("Terca-feira", "07:00", "CIRCO", 7),
        ("Terca-feira", "07:00", "SPIN FIT", 7),
        ("Terca-feira", "09:00", "NEOKIDS", 7),
        ("Terca-feira", "16:00", "NEOKIDS", 7),
        ("Terca-feira", "18:00", "STEP DANCE", 7),
        ("Terca-feira", "18:00", "CIRCO", 7),
        ("Terca-feira", "19:00", "FIT DANCE", 7),
        ("Terca-feira", "19:00", "C.FIGHT", 7),

        ("Quarta-feira", "07:00", "NEOPILATES", 7),
        ("Quarta-feira", "08:00", "ACROYOGA", 7),
        ("Quarta-feira", "16:00", "NEOPILATES", 7),
        ("Quarta-feira", "17:00", "ACROYOGA", 7),
        ("Quarta-feira", "18:00", "NEOPILATES", 7),
        ("Quarta-feira", "18:00", "SPIN FIT", 7),
        ("Quarta-feira", "19:00", "CIRCO", 7),
        ("Quarta-feira", "19:00", "UP WORK", 7),
        ("Quarta-feira", "20:00", "ACROYOGA", 7),

        ("Quinta-feira", "05:00", "NEOPILATES", 7),
        ("Quinta-feira", "07:00", "CIRCO", 7),
        ("Quinta-feira", "07:00", "SPIN FIT", 7),
        ("Quinta-feira", "09:00", "NEOKIDS", 7),
        ("Quinta-feira", "16:00", "NEOKIDS", 7),
        ("Quinta-feira", "18:00", "STEP DANCE", 7),
        ("Quinta-feira", "18:00", "CIRCO", 7),
        ("Quinta-feira", "19:00", "FIT DANCE", 7),
        ("Quinta-feira", "19:00", "C.FIGHT", 7),

        ("Sexta-feira", "05:00", "LEG WORK", 7),
        ("Sexta-feira", "07:00", "FLEX FIT", 7),
        ("Sexta-feira", "08:00", "ACROYOGA", 7),
        ("Sexta-feira", "17:00", "CROSS FIGHT", 7),
        ("Sexta-feira", "18:00", "SPIN FIT", 7),
    ])

    return aulas


def sincronizar_aulas_padrao(cursor):
    aulas_padrao = montar_aulas_padrao()
    chaves_padrao = {(dia, horario, modalidade) for dia, horario, modalidade, _ in aulas_padrao}

    for dia, horario, modalidade, capacidade in aulas_padrao:
        cursor.execute("""
            SELECT id
            FROM aulas
            WHERE dia_semana = %s AND horario = %s AND modalidade = %s
            ORDER BY id
            LIMIT 1
        """, (dia, horario, modalidade))
        aula = cursor.fetchone()

        if aula:
            cursor.execute("""
                UPDATE aulas
                SET capacidade = %s
                WHERE id = %s
            """, (capacidade, aula["id"]))
        else:
            cursor.execute("""
                INSERT INTO aulas (dia_semana, horario, modalidade, capacidade)
                VALUES (%s, %s, %s, %s)
            """, (dia, horario, modalidade, capacidade))

    cursor.execute("SELECT id, dia_semana, horario, modalidade FROM aulas")
    for aula in cursor.fetchall():
        chave = (aula["dia_semana"], aula["horario"], aula["modalidade"])
        if chave in chaves_padrao:
            continue

        cursor.execute("""
            DELETE FROM aulas
            WHERE id = %s
        """, (aula["id"],))


def aula_eh_musculacao(aula):
    return aula and aula["modalidade"] == "MUSCULACAO"


def normalizar_tipo_bloqueio(tipo):
    tipo = str(tipo or "TODAS").upper().strip()
    if tipo in ("AULAS", "MUSCULACAO"):
        return tipo
    return "TODAS"


def obter_bloqueios_aulas(cursor, data_agendamento):
    cursor.execute("""
        SELECT data_bloqueio, horario_inicio, horario_fim, motivo, tipo
        FROM bloqueios_aulas
        WHERE data_bloqueio = %s
    """, (data_agendamento,))
    return cursor.fetchall()


def obter_bloqueio_para_aula(aula, bloqueios):
    if not aula or not bloqueios:
        return None

    tipo_aula = "MUSCULACAO" if aula_eh_musculacao(aula) else "AULAS"
    bloqueio_todas = None

    for bloqueio in bloqueios:
        tipo = normalizar_tipo_bloqueio(bloqueio.get("tipo"))
        if tipo == tipo_aula:
            return bloqueio
        if tipo == "TODAS":
            bloqueio_todas = bloqueio

    return bloqueio_todas


def aula_bloqueada_por_horario(aula, bloqueio):
    if not bloqueio:
        return False

    if aula["horario"] < bloqueio["horario_inicio"]:
        return False

    if bloqueio.get("horario_fim"):
        return aula["horario"] < bloqueio["horario_fim"]

    return True


def bloqueio_fecha_resto_do_dia(bloqueio):
    return bloqueio and not bloqueio.get("horario_fim")


def init_db():
    conn = conectar()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS alunos (
            id SERIAL PRIMARY KEY,
            nome TEXT,
            telefone TEXT,
            plano TEXT,
            vencimento TEXT,
            status_pagamento TEXT,
            observacao TEXT,
            aulas_restantes INTEGER DEFAULT 12,
            usuario TEXT,
            senha TEXT,
            data_nascimento TEXT,
            aulas_contratadas INTEGER
        )
    """)

    cursor.execute("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'alunos' AND column_name = 'aulas_contratadas'
    """)
    coluna = cursor.fetchone()
    if not coluna:
        cursor.execute("ALTER TABLE alunos ADD COLUMN aulas_contratadas INTEGER")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS aulas (
            id SERIAL PRIMARY KEY,
            dia_semana TEXT,
            horario TEXT,
            modalidade TEXT,
            capacidade INTEGER DEFAULT 10
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS agendamentos (
            id SERIAL PRIMARY KEY,
            aluno_id INTEGER,
            aula_id INTEGER,
            data_agendamento TEXT,
            UNIQUE(aluno_id, aula_id, data_agendamento)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bloqueios_aulas (
            data_bloqueio TEXT,
            horario_inicio TEXT,
            horario_fim TEXT,
            tipo TEXT DEFAULT 'TODAS',
            motivo TEXT
        )
    """)

    cursor.execute("""
        ALTER TABLE bloqueios_aulas ADD COLUMN IF NOT EXISTS horario_fim TEXT
    """)

    cursor.execute("""
        ALTER TABLE bloqueios_aulas ADD COLUMN IF NOT EXISTS tipo TEXT DEFAULT 'TODAS'
    """)

    cursor.execute("""
        UPDATE bloqueios_aulas SET tipo = 'TODAS' WHERE tipo IS NULL OR tipo = ''
    """)

    cursor.execute("""
        ALTER TABLE bloqueios_aulas DROP CONSTRAINT IF EXISTS bloqueios_aulas_pkey
    """)

    cursor.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_bloqueios_aulas_data_tipo
        ON bloqueios_aulas (data_bloqueio, tipo)
    """)

    cursor.execute("""
        ALTER TABLE alunos ADD COLUMN IF NOT EXISTS data_inicio TEXT
    """)

    cursor.execute("""
    ALTER TABLE alunos ADD COLUMN IF NOT EXISTS aulas_contratadas INTEGER
""")
    
    cursor.execute("""
    ALTER TABLE alunos ADD COLUMN IF NOT EXISTS aceitou_contrato BOOLEAN DEFAULT FALSE
""")

    cursor.execute("""
    ALTER TABLE alunos ADD COLUMN IF NOT EXISTS data_aceite_contrato TEXT
""")
    
    cursor.execute("""
    ALTER TABLE alunos ADD COLUMN IF NOT EXISTS frequencia TEXT
""")

    cursor.execute("""
    ALTER TABLE alunos ADD COLUMN IF NOT EXISTS limite_diario INTEGER
""")
    
    cursor.execute("""
    ALTER TABLE alunos ADD COLUMN IF NOT EXISTS aulas_usadas_iniciais INTEGER DEFAULT 0
""")

    conn.commit()

    sincronizar_aulas_padrao(cursor)
    conn.commit()

    conn.close()

from datetime import datetime, timedelta

from datetime import datetime, timedelta


def obter_horario_bloqueio(data_bloqueio):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT horario_inicio, horario_fim, tipo
        FROM bloqueios_aulas
        WHERE data_bloqueio = %s
    """, (data_bloqueio.strftime("%Y-%m-%d"),))
    bloqueios = cursor.fetchall()
    conn.close()

    bloqueios_resto_dia = [
        bloqueio for bloqueio in bloqueios
        if not bloqueio.get("horario_fim")
    ]

    for bloqueio in bloqueios_resto_dia:
        if normalizar_tipo_bloqueio(bloqueio.get("tipo")) == "TODAS":
            return bloqueio["horario_inicio"]

    tipos = {
        normalizar_tipo_bloqueio(bloqueio.get("tipo"))
        for bloqueio in bloqueios_resto_dia
    }

    if {"AULAS", "MUSCULACAO"}.issubset(tipos):
        return min(bloqueio["horario_inicio"] for bloqueio in bloqueios_resto_dia)

    return None


def obter_data_base():
    agora = datetime.utcnow() - timedelta(hours=3)
    horario_bloqueio = obter_horario_bloqueio(agora.date())

    if horario_bloqueio and agora.strftime("%H:%M") >= horario_bloqueio:
        return agora.date() + timedelta(days=1)

    # domingo = 6 
    if   agora.weekday() == 6:
        if agora.hour >= 12:
            return agora.date() + timedelta(days=1)

    else:
        if (agora.hour, agora.minute) >= (20, 45):
            return agora.date() + timedelta(days=1)

    return agora.date()

def obter_data_cronograma_formatada():
    data_base = obter_data_base()
    return data_base.strftime("%d/%m/%Y")

def obter_dia_semana():
    data_base = obter_data_base()

    mapa = {
        0: "Segunda-feira",
        1: "Terca-feira",
        2: "Quarta-feira",
        3: "Quinta-feira",
        4: "Sexta-feira",
        5: "Sabado",
        6: "Domingo",
    }

    return mapa[data_base.weekday()]


def listar_aulas_do_dia(dia_semana=None):
    if not dia_semana:
        dia_semana = obter_dia_semana()

    conn = conectar()
    cursor = conn.cursor()
    data_base = obter_data_base()
    hoje = data_base.strftime("%Y-%m-%d")

    cursor.execute("""
        SELECT 
            a.id, 
            a.dia_semana, 
            a.horario, 
            a.modalidade, 
            a.capacidade,
            COUNT(ag.id) AS ocupadas
        FROM aulas a
        LEFT JOIN agendamentos ag 
            ON ag.aula_id = a.id 
            AND ag.data_agendamento = %s
        WHERE a.dia_semana = %s
        GROUP BY a.id, a.dia_semana, a.horario, a.modalidade, a.capacidade
        ORDER BY a.horario
    """, (hoje, dia_semana))
    aulas = cursor.fetchall()
    bloqueios = obter_bloqueios_aulas(cursor, hoje)

    dados = []
    for aula in aulas:
        ocupadas = aula["ocupadas"] or 0
        capacidade = aula["capacidade"] or 10

        cursor.execute("""
            SELECT 
                ag.id AS agendamento_id,
                al.nome,
                al.data_nascimento
            FROM agendamentos ag
            JOIN alunos al ON al.id = ag.aluno_id
            WHERE ag.aula_id = %s AND ag.data_agendamento = %s
            ORDER BY al.nome ASC
        """, (aula["id"], hoje))

        inscritos_db = cursor.fetchall()

        inscritos = [
            {
                "agendamento_id": i["agendamento_id"],
                "nome": i["nome"],
                "idade": calcular_idade(i["data_nascimento"])
            }
            for i in inscritos_db
        ]

        item = dict(aula)
        item["restantes"] = max(capacidade - ocupadas, 0)
        item["percentual"] = int((ocupadas / capacidade) * 100) if capacidade else 0
        item["lotada"] = ocupadas >= capacidade
        bloqueio = obter_bloqueio_para_aula(aula, bloqueios)
        item["bloqueada"] = aula_bloqueada_por_horario(aula, bloqueio)
        item["horario_bloqueio"] = bloqueio["horario_inicio"] if bloqueio else None
        item["horario_fim_bloqueio"] = bloqueio["horario_fim"] if bloqueio else None
        item["motivo_bloqueio"] = bloqueio["motivo"] if bloqueio else None
        item["tipo_bloqueio"] = bloqueio["tipo"] if bloqueio else None
        item["inscritos"] = inscritos
        dados.append(item)

    conn.close()
    return dia_semana, dados


@app.route("/")
def home():
    if "admin_logado" in session:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    erro = None
    if request.method == "POST":
        if request.form["usuario"] == "dlfit" and request.form["senha"] == "academia@2026":
            session["admin_logado"] = True
            session.pop("professor_liberado", None)
            return redirect(url_for("dashboard"))
        erro = "Usuario ou senha invalidos"
    return render_template("login.html", erro=erro)


@app.route("/logout")
def logout():
    session.pop("admin_logado", None)
    session.pop("professor_liberado", None)
    return redirect(url_for("login"))


@app.route("/dashboard")
def dashboard():
    if "admin_logado" not in session:
        return redirect(url_for("login"))

    conn = conectar()
    cursor = conn.cursor()
    manutencao_basica_segura(conn, cursor, limpar_bloqueios=True)

    cursor.execute("SELECT COUNT(*) AS total FROM alunos")
    total = cursor.fetchone()["total"]

    cursor.execute("SELECT COUNT(*) AS total FROM alunos WHERE status_pagamento = 'Pago'")
    pagos = cursor.fetchone()["total"]

    cursor.execute("SELECT COUNT(*) AS total FROM alunos WHERE status_pagamento = 'Pendente'")
    pendentes = cursor.fetchone()["total"]

    cursor.execute("SELECT COUNT(*) AS total FROM alunos WHERE status_pagamento = 'Atrasado'")
    atrasados = cursor.fetchone()["total"]

    cursor.execute("SELECT * FROM alunos ORDER BY nome ASC")
    alunos = cursor.fetchall()

    cursor.execute("""
        SELECT data_bloqueio, horario_inicio, horario_fim, motivo, tipo
        FROM bloqueios_aulas
        WHERE data_bloqueio >= %s
        ORDER BY data_bloqueio ASC, horario_inicio ASC, tipo ASC
        LIMIT 10
    """, (data_hoje_brasil().strftime("%Y-%m-%d"),))
    bloqueios_aulas = cursor.fetchall()

    dia_atual, aulas_hoje = listar_aulas_do_dia()
    conn.close()

    return render_template(
        "dashboard.html",
        total=total,
        pagos=pagos,
        pendentes=pendentes,
        atrasados=atrasados,
        alunos=alunos,
        dia_atual=dia_atual,
        aulas_hoje=aulas_hoje,
        bloqueios_aulas=bloqueios_aulas,
        data_padrao_bloqueio=obter_data_base().strftime("%Y-%m-%d")
    )


@app.route("/dev-backup-dlfit")
def dev_backup():
    if "admin_logado" not in session:
        return redirect(url_for("login"))

    return render_template(
        "dev_backup.html",
        erro=request.args.get("erro", ""),
        sucesso=request.args.get("sucesso", "")
    )


@app.route("/baixar_backup")
def baixar_backup():
    if "admin_logado" not in session:
        return redirect(url_for("login"))

    conn = conectar()
    cursor = conn.cursor()
    atualizar_status_vencidos(cursor)
    unificar_alunos_duplicados(cursor)
    limpar_bloqueios_antigos(cursor)
    conn.commit()

    arquivo = BytesIO()
    with pd.ExcelWriter(arquivo, engine="openpyxl") as writer:
        for tabela, colunas in TABELAS_BACKUP.items():
            cursor.execute(f"SELECT {', '.join(colunas)} FROM {tabela}")
            dados = cursor.fetchall()
            df = pd.DataFrame(dados, columns=colunas)
            df.to_excel(writer, sheet_name=tabela, index=False)

    conn.close()
    arquivo.seek(0)

    nome_arquivo = f"backup_dlfit_{data_hoje_brasil().strftime('%Y-%m-%d')}.xlsx"
    return send_file(
        arquivo,
        as_attachment=True,
        download_name=nome_arquivo,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


@app.route("/restaurar_backup", methods=["GET", "POST"])
def restaurar_backup():
    conn = None

    try:
        if "admin_logado" not in session:
            return redirect(url_for("login"))

        if request.method != "POST":
            return redirect(url_for("dev_backup"))

        arquivo = request.files.get("arquivo_backup")
        if not arquivo or arquivo.filename == "":
            return redirect(url_for("dev_backup", erro="Selecione um arquivo de backup em Excel."))

        abas = pd.read_excel(arquivo, sheet_name=None, engine="openpyxl")
        conn = conectar()
        cursor = conn.cursor()

        cursor.execute("DELETE FROM agendamentos")
        cursor.execute("DELETE FROM bloqueios_aulas")
        cursor.execute("DELETE FROM aulas")
        cursor.execute("DELETE FROM alunos")

        for tabela in ("alunos", "aulas", "agendamentos", "bloqueios_aulas"):
            if tabela not in abas:
                continue

            df = abas[tabela]
            colunas = [
                coluna for coluna in TABELAS_BACKUP[tabela]
                if coluna in df.columns
            ]
            if colunas:
                inserir_linhas_backup(cursor, tabela, colunas, df)

        for tabela in ("alunos", "aulas", "agendamentos"):
            resetar_sequence(cursor, tabela)

        atualizar_status_vencidos(cursor)
        unificar_alunos_duplicados(cursor)
        conn.commit()
    except Exception as e:
        if conn:
            conn.rollback()
        return redirect(url_for("dev_backup", erro=f"Erro ao restaurar backup: {e}"))
    finally:
        if conn:
            conn.close()

    return redirect(url_for("dev_backup", sucesso="Backup restaurado com sucesso."))


@app.route("/bloqueio_aulas", methods=["POST"])
def bloqueio_aulas():
    if "admin_logado" not in session:
        return redirect(url_for("login"))

    data_bloqueio = request.form.get("data_bloqueio", "")
    horario_inicio = request.form.get("horario_inicio", "")
    horario_fim = request.form.get("horario_fim", "")
    tipo = normalizar_tipo_bloqueio(request.form.get("tipo_bloqueio", "TODAS"))
    motivo = request.form.get("motivo", "")

    if horario_fim and horario_fim <= horario_inicio:
        horario_fim = ""

    if data_bloqueio and data_bloqueio < data_hoje_brasil().strftime("%Y-%m-%d"):
        return redirect(url_for("dashboard"))

    if data_bloqueio and horario_inicio:
        conn = conectar()
        cursor = conn.cursor()
        limpar_bloqueios_antigos(cursor)
        cursor.execute("""
            INSERT INTO bloqueios_aulas (data_bloqueio, horario_inicio, horario_fim, tipo, motivo)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (data_bloqueio, tipo)
            DO UPDATE SET horario_inicio = EXCLUDED.horario_inicio,
                          horario_fim = EXCLUDED.horario_fim,
                          motivo = EXCLUDED.motivo
        """, (data_bloqueio, horario_inicio, horario_fim or None, tipo, motivo))
        conn.commit()
        conn.close()

    return redirect(url_for("dashboard"))


@app.route("/remover_bloqueio_aulas/<data_bloqueio>/<tipo>", methods=["POST"])
def remover_bloqueio_aulas(data_bloqueio, tipo):
    if "admin_logado" not in session:
        return redirect(url_for("login"))

    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM bloqueios_aulas WHERE data_bloqueio = %s AND tipo = %s",
        (data_bloqueio, normalizar_tipo_bloqueio(tipo))
    )
    conn.commit()
    conn.close()

    return redirect(url_for("dashboard"))


@app.route("/alunos")
def alunos():
    if "admin_logado" not in session:
        return redirect(url_for("login"))

    busca = request.args.get("busca", "").strip()
    status = request.args.get("status", "").strip()
    conn = conectar()
    cursor = conn.cursor()
    manutencao_basica_segura(conn, cursor)

    if busca and status:
        cursor.execute(
            "SELECT * FROM alunos WHERE nome ILIKE %s AND status_pagamento = %s ORDER BY nome ASC",
            (f"%{busca}%", status)
        )
        alunos = cursor.fetchall()
    elif busca:
        cursor.execute("SELECT * FROM alunos WHERE nome ILIKE %s ORDER BY nome ASC", (f"%{busca}%",))
        alunos = cursor.fetchall()
    elif status:
        cursor.execute("SELECT * FROM alunos WHERE status_pagamento = %s ORDER BY nome ASC", (status,))
        alunos = cursor.fetchall()
    else:
        cursor.execute("SELECT * FROM alunos ORDER BY nome ASC")
        alunos = cursor.fetchall()

    preencher_resumo_aulas_lista(cursor, alunos)

    conn.close()
    return render_template(
        "alunos.html",
        alunos=alunos,
        busca=busca,
        status=status,
        calcular_idade=calcular_idade,
        formatar_data_brasil=formatar_data_brasil
    )


@app.route("/excluir_todos_alunos")
def excluir_todos_alunos():
    if "admin_logado" not in session:
        return redirect(url_for("login"))

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute("DELETE FROM agendamentos")
    cursor.execute("DELETE FROM alunos")

    conn.commit()
    conn.close()

    return redirect(url_for("alunos"))

@app.route("/novo_aluno", methods=["GET", "POST"])
def novo_aluno():
    if "admin_logado" not in session:
        return redirect(url_for("login"))

    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        if not nome:
            return redirect(url_for("novo_aluno"))

        usuario = remover_acentos(nome.split()[0].lower())

        conn = conectar()
        cursor = conn.cursor()
        data_inicio = request.form.get("data_inicio", "")
        vencimento = request.form.get("vencimento", "")
        frequencia = request.form.get("frequencia", "")
        aulas_contratadas = obter_aulas_contratadas_form(
            data_inicio,
            vencimento,
            frequencia
        )

        cursor.execute("""
            INSERT INTO alunos (
                nome, telefone, plano, vencimento, status_pagamento,
                observacao, aulas_restantes, usuario, senha, data_nascimento,
                data_inicio, aulas_contratadas, frequencia, aulas_usadas_iniciais
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            nome,
            request.form.get("telefone", ""),
            request.form.get("plano", "").upper().strip(),
            vencimento,
            request.form.get("status_pagamento", ""),
            request.form.get("observacao", ""),
            12,
            usuario,
            "1234",
            request.form.get("data_nascimento", ""),
            data_inicio,
            aulas_contratadas,
            frequencia,
            request.form.get("aulas_usadas_iniciais") or 0
        ))

        unificar_alunos_duplicados(cursor)
        conn.commit()
        conn.close()
        return redirect(url_for("alunos"))

    return render_template("novo_aluno.html")


@app.route("/editar_aluno/<int:id>", methods=["GET", "POST"])
def editar_aluno(id):
    if "admin_logado" not in session:
        return redirect(url_for("login"))

    conn = conectar()
    cursor = conn.cursor()

    if request.method == "POST":
        cursor.execute("SELECT * FROM alunos WHERE id = %s", (id,))
        aluno_atual = cursor.fetchone()

        nome = request.form.get("nome", "").strip()
        if not nome:
            conn.close()
            return redirect(url_for("editar_aluno", id=id))

        data_inicio = request.form.get("data_inicio", "")
        vencimento = request.form.get("vencimento", "")
        status_pagamento = request.form.get("status_pagamento", "")
        frequencia = request.form.get("frequencia", "")
        aulas_usadas_iniciais = request.form.get("aulas_usadas_iniciais") or 0
        renovacao_plano = (
            aluno_atual
            and status_pagamento == "Pago"
            and vencimento
            and vencimento != (aluno_atual["vencimento"] or "")
        )

        if (
            renovacao_plano
            and data_inicio == (aluno_atual["data_inicio"] or "")
        ):
            data_inicio = (datetime.utcnow() - timedelta(hours=3)).strftime("%Y-%m-%d")

        if renovacao_plano:
            aulas_usadas_iniciais = 0

        aulas_contratadas = obter_aulas_contratadas_form(
            data_inicio,
            vencimento,
            frequencia
        )

        cursor.execute("""
            UPDATE alunos
            SET nome=%s, telefone=%s, plano=%s, vencimento=%s,
                status_pagamento=%s, observacao=%s, data_nascimento=%s,
                data_inicio=%s, aulas_contratadas=%s, frequencia=%s,
                aulas_usadas_iniciais=%s
            WHERE id=%s
        """, (
            nome,
            request.form.get("telefone", ""),
            request.form.get("plano", "").upper().strip(),
            vencimento,
            status_pagamento,
            request.form.get("observacao", ""),
            request.form.get("data_nascimento", ""),
            data_inicio,
            aulas_contratadas,
            frequencia,
            aulas_usadas_iniciais,
            id
        ))
        unificar_alunos_duplicados(cursor)
        conn.commit()
        conn.close()
        return redirect(url_for("alunos"))

    cursor.execute("SELECT * FROM alunos WHERE id = %s", (id,))
    aluno = cursor.fetchone()
    conn.close()
    return render_template("editar_aluno.html", aluno=aluno)


@app.route("/excluir_aluno/<int:id>")
def excluir_aluno(id):
    if "admin_logado" not in session:
        return redirect(url_for("login"))

    conn = conectar()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM agendamentos WHERE aluno_id = %s", (id,))
    cursor.execute("DELETE FROM alunos WHERE id = %s", (id,))
    conn.commit()
    conn.close()
    return redirect(url_for("alunos"))


@app.route("/importar_excel", methods=["GET", "POST"])
def importar_excel():
    if "admin_logado" not in session:
        return redirect(url_for("login"))

    erro = None
    if request.method == "POST":
        arquivo = request.files.get("arquivo")

        if not arquivo or arquivo.filename == "":
            erro = "Selecione um arquivo Excel."
        else:
            try:
                df = pd.read_excel(arquivo, engine="openpyxl")
                conn = conectar()
                cursor = conn.cursor()

                for _, row in df.iterrows():
                    nome = str(row.get("Nome", "")).strip()
                    if not nome or nome.lower() == "nan":
                        continue

                    usuario = remover_acentos(nome.split()[0].lower())

                    telefone = "" if pd.isna(row.get("Telefone")) else str(row.get("Telefone"))
                    plano = "" if pd.isna(row.get("Plano")) else str(row.get("Plano"))
                    vencimento = "" if pd.isna(row.get("Vencimento")) else str(row.get("Vencimento"))
                    status = "Pendente" if pd.isna(row.get("Status")) else str(row.get("Status"))
                    observacao = "" if pd.isna(row.get("Observacao")) else str(row.get("Observacao"))
                    data_nascimento = "" if pd.isna(row.get("DataNascimento")) else str(row.get("DataNascimento"))
                    data_inicio = "" if pd.isna(row.get("DataInicio")) else str(row.get("DataInicio"))
                    aulas_contratadas = None if pd.isna(row.get("AulasContratadas")) else int(row.get("AulasContratadas"))
                    frequencia = "" if pd.isna(row.get("Frequencia")) else str(row.get("Frequencia"))
                    aulas_usadas_iniciais = 0 if pd.isna(row.get("AulasUsadasIniciais")) else int(row.get("AulasUsadasIniciais"))

                    cursor.execute("""
                        INSERT INTO alunos (
                            nome, telefone, plano, vencimento, status_pagamento,
                            observacao, aulas_restantes, usuario, senha, data_nascimento,
                            data_inicio, aulas_contratadas, frequencia, aulas_usadas_iniciais
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        nome,
                        telefone,
                        plano,
                        vencimento,
                        status,
                        observacao,
                        12,
                        usuario,
                        "1234",
                        data_nascimento,
                        data_inicio,
                        aulas_contratadas,
                        frequencia,
                        aulas_usadas_iniciais
                    ))

                unificar_alunos_duplicados(cursor)
                conn.commit()
                conn.close()
                return redirect(url_for("alunos"))
            except Exception as e:
                erro = f"Erro ao importar: {e}"

    return render_template("importar.html", erro=erro)


@app.route("/cronograma")
def cronograma():
    dia_atual, aulas_hoje = listar_aulas_do_dia()
    data_cronograma = obter_data_cronograma_formatada()

    conn = conectar()
    cursor = conn.cursor()
    atualizar_status_vencidos(cursor)
    unificar_alunos_duplicados(cursor)
    conn.commit()
    cursor.execute("SELECT * FROM alunos ORDER BY nome ASC")
    alunos = cursor.fetchall()
    conn.close()

    return render_template(
        "cronograma.html",
        dia_atual=dia_atual,
        data_cronograma=data_cronograma,
        aulas_hoje=aulas_hoje,
        alunos=alunos,
        modo_professor=False
    )


@app.route("/painel_professor")
def painel_professor():
    if "admin_logado" not in session and "professor_liberado" not in session:
        return redirect(url_for("cronograma"))

    dia_atual, aulas_hoje = listar_aulas_do_dia()
    data_cronograma = obter_data_cronograma_formatada()

    conn = conectar()
    cursor = conn.cursor()
    atualizar_status_vencidos(cursor)
    unificar_alunos_duplicados(cursor)
    conn.commit()
    cursor.execute("SELECT * FROM alunos ORDER BY nome ASC")
    alunos = cursor.fetchall()
    conn.close()

    return render_template(
        "cronograma.html",
        dia_atual=dia_atual,
        data_cronograma=data_cronograma,
        aulas_hoje=aulas_hoje,
        alunos=alunos,
        modo_professor=True
    )


@app.route("/agendar_aula/<int:aula_id>", methods=["POST"])
def agendar_aula(aula_id):
    nome_digitado = request.form.get("nome_aluno", "")
    voltar_dashboard = (
        request.form.get("voltar") == "dashboard"
        and "admin_logado" in session
    )

    conn = conectar()
    cursor = conn.cursor()
    atualizar_status_vencidos(cursor)
    unificar_alunos_duplicados(cursor)
    conn.commit()

    cursor.execute("SELECT * FROM alunos ORDER BY nome ASC")
    nome_normalizado = normalizar_nome(nome_digitado)
    aluno = next(
        (item for item in cursor.fetchall() if normalizar_nome(item["nome"]) == nome_normalizado),
        None
    )

    if not aluno:
        conn.close()
        return render_template(
            "mensagem.html",
            titulo="Aluno nao encontrado",
            mensagem="Nao encontramos esse nome no cadastro. Digite o nome completo ou selecione o nome na lista."
        )

    aluno_id = aluno["id"]

    

    # buscar aula
    cursor.execute("SELECT * FROM aulas WHERE id = %s", (aula_id,))
    aula = cursor.fetchone()

    if not aula:
        conn.close()
        return redirect(url_for("cronograma"))

    # 🚫 bloqueio por pagamento
    if aluno["status_pagamento"] == "Atrasado":
        conn.close()
        return render_template(
            "mensagem.html",
            titulo="Aula nao marcada",
            mensagem="Aula nao marcada porque o pagamento esta em atraso. Procure a administracao da academia para regularizar."
        )

    agora = datetime.utcnow() - timedelta(hours=3)
    bloqueios_hoje = obter_bloqueios_aulas(cursor, agora.strftime("%Y-%m-%d"))
    bloqueio_hoje = obter_bloqueio_para_aula(aula, bloqueios_hoje)
    if bloqueio_fecha_resto_do_dia(bloqueio_hoje) and agora.strftime("%H:%M") >= bloqueio_hoje["horario_inicio"]:
        conn.close()
        return render_template(
            "mensagem.html",
            titulo="Cronograma atualizado",
            mensagem="O horario de fechamento especial foi atingido. Volte ao cronograma para ver as aulas do dia seguinte."
        )

    data_base = obter_data_base()
    data_agendamento = data_base.strftime("%Y-%m-%d")

    bloqueios = obter_bloqueios_aulas(cursor, data_agendamento)
    bloqueio = obter_bloqueio_para_aula(aula, bloqueios)
    if aula_bloqueada_por_horario(aula, bloqueio):
        conn.close()
        return render_template(
            "mensagem.html",
            titulo="Aula bloqueada",
            mensagem="A academia tera fechamento especial neste dia. Esta aula nao esta disponivel para agendamento."
        )

    # vagas ocupadas
    cursor.execute("""
        SELECT COUNT(*) AS total
        FROM agendamentos
        WHERE aula_id = %s AND data_agendamento = %s
    """, (aula_id, data_agendamento))
    ocupadas = cursor.fetchone()["total"]

    aulas_usadas_sistema = contar_aulas_usadas(cursor, aluno_id, aluno["data_inicio"])
    aulas_usadas_total = aulas_usadas_sistema + (aluno["aulas_usadas_iniciais"] or 0)

    limite = limite_plano(aluno["plano"], aluno["aulas_contratadas"])

    if limite < 9999 and aulas_usadas_total >= limite:
        conn.close()
        return render_template(
            "mensagem.html",
            titulo="Aula nao marcada",
            mensagem="Aula nao marcada porque o aluno esta sem aulas restantes. Procure a administracao da academia para liberar novas aulas."
        )

    if ocupadas >= aula["capacidade"]:
        conn.close()
        return render_template(
        "mensagem.html",
        titulo="Aula lotada",
        mensagem="Esta aula já atingiu o limite de vagas disponíveis."
    )

    # evitar duplicado
    cursor.execute("""
        SELECT 1
        FROM agendamentos
        WHERE aluno_id = %s AND aula_id = %s AND data_agendamento = %s
    """, (aluno_id, aula_id, data_agendamento))

    if cursor.fetchone():
        conn.close()
        if voltar_dashboard:
            return redirect(url_for("dashboard"))
        return redirect(url_for("cronograma"))
    
    if not aluno["aceitou_contrato"] and not voltar_dashboard:
        session["aluno_pendente_contrato"] = aluno["id"]
        session["aula_pendente_contrato"] = aula_id
        conn.close()
        return redirect(url_for("contrato_aluno"))

    # salvar
    cursor.execute("""
        INSERT INTO agendamentos (aluno_id, aula_id, data_agendamento)
        VALUES (%s, %s, %s)
    """, (aluno_id, aula_id, data_agendamento))

    conn.commit()
    aulas_usadas_sistema = aulas_usadas_sistema + 1
    aulas_usadas_total = aulas_usadas_sistema + (aluno["aulas_usadas_iniciais"] or 0)
    restantes = max(limite - aulas_usadas_total, 0)
    conn.close()

    if voltar_dashboard:
        return redirect(url_for("dashboard"))

    return render_template(
    "agendamento_sucesso.html",
    aulas_usadas=aulas_usadas_total,
    aulas_total=limite,
    aulas_restantes=restantes,
    vencimento=aluno["vencimento"]
)


@app.route("/acesso_professor", methods=["POST"])
def acesso_professor():
    senha = request.form.get("senha_professor", "")
    if senha == "dlfit":
        session["professor_liberado"] = True
        return redirect(url_for("painel_professor"))
    return redirect(url_for("cronograma"))


@app.route("/sair_professor")
def sair_professor():
    session.pop("professor_liberado", None)
    return redirect(url_for("cronograma"))

@app.route("/contrato_aluno")
def contrato_aluno():
    if "aluno_pendente_contrato" not in session:
        return redirect(url_for("cronograma"))

    return render_template("contrato_aluno.html")

@app.route("/aceitar_contrato", methods=["POST"])
def aceitar_contrato():
    aluno_id = session.get("aluno_pendente_contrato")
    aula_id = session.get("aula_pendente_contrato")

    if not aluno_id or not aula_id:
        return redirect(url_for("cronograma"))

    conn = conectar()
    cursor = conn.cursor()
    atualizar_status_vencidos(cursor)
    conn.commit()

    cursor.execute("SELECT * FROM alunos WHERE id = %s", (aluno_id,))
    aluno = cursor.fetchone()

    if aluno and aluno["status_pagamento"] == "Atrasado":
        conn.close()
        session.pop("aluno_pendente_contrato", None)
        session.pop("aula_pendente_contrato", None)
        return render_template(
            "mensagem.html",
            titulo="Aula nao marcada",
            mensagem="Aula nao marcada porque o pagamento esta em atraso. Procure a administracao da academia para regularizar."
        )

    cursor.execute("""
        UPDATE alunos
        SET aceitou_contrato = TRUE,
            data_aceite_contrato = %s
        WHERE id = %s
    """, (
        (datetime.utcnow() - timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S"),
        aluno_id
    ))

    cursor.execute("SELECT * FROM aulas WHERE id = %s", (aula_id,))
    aula = cursor.fetchone()

    agora = datetime.utcnow() - timedelta(hours=3)
    bloqueios_hoje = obter_bloqueios_aulas(cursor, agora.strftime("%Y-%m-%d"))
    bloqueio_hoje = obter_bloqueio_para_aula(aula, bloqueios_hoje)
    if bloqueio_fecha_resto_do_dia(bloqueio_hoje) and agora.strftime("%H:%M") >= bloqueio_hoje["horario_inicio"]:
        conn.commit()
        conn.close()
        session.pop("aluno_pendente_contrato", None)
        session.pop("aula_pendente_contrato", None)
        return render_template(
            "mensagem.html",
            titulo="Cronograma atualizado",
            mensagem="O horario de fechamento especial foi atingido. Volte ao cronograma para ver as aulas do dia seguinte."
        )

    data_base = obter_data_base()
    data_agendamento = data_base.strftime("%Y-%m-%d")

    bloqueios = obter_bloqueios_aulas(cursor, data_agendamento)
    bloqueio = obter_bloqueio_para_aula(aula, bloqueios)
    if aula and aula_bloqueada_por_horario(aula, bloqueio):
        conn.close()
        session.pop("aluno_pendente_contrato", None)
        session.pop("aula_pendente_contrato", None)
        return render_template(
            "mensagem.html",
            titulo="Aula bloqueada",
            mensagem="A academia tera fechamento especial neste dia. Esta aula nao esta disponivel para agendamento."
        )

    cursor.execute("""
        INSERT INTO agendamentos (aluno_id, aula_id, data_agendamento)
        VALUES (%s, %s, %s)
        ON CONFLICT DO NOTHING
    """, (aluno_id, aula_id, data_agendamento))

    conn.commit()

    cursor.execute("SELECT * FROM alunos WHERE id = %s", (aluno_id,))
    aluno = cursor.fetchone()

    aulas_usadas_sistema = contar_aulas_usadas(cursor, aluno_id, aluno["data_inicio"])

    limite = limite_plano(aluno["plano"], aluno["aulas_contratadas"])
    aulas_usadas_total = aulas_usadas_sistema + (aluno["aulas_usadas_iniciais"] or 0)

    if limite >= 9999:
        restantes = 9999
    else:
        restantes = max(limite - aulas_usadas_total, 0)

    conn.close()

    session.pop("aluno_pendente_contrato", None)
    session.pop("aula_pendente_contrato", None)

    return render_template(
        "agendamento_sucesso.html",
        aulas_usadas=aulas_usadas_total,
        aulas_total=limite,
        aulas_restantes=restantes,
        vencimento=aluno["vencimento"]
    )

@app.route("/remover_agendamento/<int:agendamento_id>")
def remover_agendamento(agendamento_id):
    if "admin_logado" not in session and "professor_liberado" not in session:
        return redirect(url_for("cronograma"))

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute("DELETE FROM agendamentos WHERE id = %s", (agendamento_id,))

    conn.commit()
    conn.close()

    if request.args.get("voltar") == "dashboard" and "admin_logado" in session:
        return redirect(url_for("dashboard"))

    return redirect(url_for("cronograma"))

init_db()

if __name__ == "__main__":
    app.run(debug=True)
