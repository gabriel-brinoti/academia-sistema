from flask import Flask, render_template, request, redirect, url_for, session
import os
import psycopg2
from psycopg2.extras import RealDictCursor
import pandas as pd
import unicodedata
from datetime import datetime, date, timedelta

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

def resumo_aulas_mes(cursor, aluno_id, plano):
    cursor.execute("""
        SELECT COUNT(*) AS total
        FROM agendamentos
        WHERE aluno_id = %s
    """, (aluno_id,))

    usadas_sistema = cursor.fetchone()["total"]

    cursor.execute("""
        SELECT aulas_contratadas, aulas_usadas_iniciais
        FROM alunos
        WHERE id = %s
    """, (aluno_id,))

    aluno = cursor.fetchone()

    limite = limite_plano(plano, aluno["aulas_contratadas"])
    usadas = usadas_sistema + (aluno["aulas_usadas_iniciais"] or 0)

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


def obter_bloqueio_aulas(cursor, data_agendamento):
    cursor.execute("""
        SELECT data_bloqueio, horario_inicio, motivo
        FROM bloqueios_aulas
        WHERE data_bloqueio = %s
    """, (data_agendamento,))
    return cursor.fetchone()


def aula_bloqueada_por_horario(aula, bloqueio):
    if not bloqueio:
        return False

    return aula["horario"] >= bloqueio["horario_inicio"]


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
            data_bloqueio TEXT PRIMARY KEY,
            horario_inicio TEXT,
            motivo TEXT
        )
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

def obter_data_base():
    agora = datetime.utcnow() - timedelta(hours=3)

    # domingo = 6 
    if   agora.weekday() == 6:
        if agora.hour >= 12:
            return agora.date() + timedelta(days=1)

    else:
        if agora.hour >= 21:
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
    bloqueio = obter_bloqueio_aulas(cursor, hoje)

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
        item["bloqueada"] = aula_bloqueada_por_horario(aula, bloqueio)
        item["horario_bloqueio"] = bloqueio["horario_inicio"] if bloqueio else None
        item["motivo_bloqueio"] = bloqueio["motivo"] if bloqueio else None
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
        SELECT data_bloqueio, horario_inicio, motivo
        FROM bloqueios_aulas
        ORDER BY data_bloqueio DESC
        LIMIT 10
    """)
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


@app.route("/bloqueio_aulas", methods=["POST"])
def bloqueio_aulas():
    if "admin_logado" not in session:
        return redirect(url_for("login"))

    data_bloqueio = request.form.get("data_bloqueio", "")
    horario_inicio = request.form.get("horario_inicio", "")
    motivo = request.form.get("motivo", "")

    if data_bloqueio and horario_inicio:
        conn = conectar()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO bloqueios_aulas (data_bloqueio, horario_inicio, motivo)
            VALUES (%s, %s, %s)
            ON CONFLICT (data_bloqueio)
            DO UPDATE SET horario_inicio = EXCLUDED.horario_inicio,
                          motivo = EXCLUDED.motivo
        """, (data_bloqueio, horario_inicio, motivo))
        conn.commit()
        conn.close()

    return redirect(url_for("dashboard"))


@app.route("/remover_bloqueio_aulas/<data_bloqueio>", methods=["POST"])
def remover_bloqueio_aulas(data_bloqueio):
    if "admin_logado" not in session:
        return redirect(url_for("login"))

    conn = conectar()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM bloqueios_aulas WHERE data_bloqueio = %s", (data_bloqueio,))
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

    for aluno in alunos:
        aluno["resumo_aulas"] = resumo_aulas_mes(cursor, aluno["id"], aluno["plano"])

    conn.close()
    return render_template(
        "alunos.html",
        alunos=alunos,
        busca=busca,
        status=status,
        calcular_idade=calcular_idade
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
            request.form.get("vencimento", ""),
            request.form.get("status_pagamento", ""),
            request.form.get("observacao", ""),
            12,
            usuario,
            "1234",
            request.form.get("data_nascimento", ""),
            request.form.get("data_inicio", ""),
            request.form.get("aulas_contratadas") or None,
            request.form.get("frequencia", ""),
            request.form.get("aulas_usadas_iniciais") or 0
        ))

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
        nome = request.form.get("nome", "").strip()
        if not nome:
            conn.close()
            return redirect(url_for("editar_aluno", id=id))

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
            request.form.get("vencimento", ""),
            request.form.get("status_pagamento", ""),
            request.form.get("observacao", ""),
            request.form.get("data_nascimento", ""),
            request.form.get("data_inicio", ""),
            request.form.get("aulas_contratadas") or None,
            request.form.get("frequencia", ""),
            request.form.get("aulas_usadas_iniciais") or 0,
            id
        ))
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
    nome_digitado = request.form["nome_aluno"]

    conn = conectar()
    cursor = conn.cursor()

    # 🔍 buscar aluno pelo nome
    cursor.execute("""
    SELECT * FROM alunos
    WHERE LOWER(nome) = LOWER(%s)
""", (nome_digitado.strip(),))

    aluno = cursor.fetchone()

    if not aluno:
        conn.close()
        return redirect(url_for("cronograma"))

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

    data_base = obter_data_base()
    data_agendamento = data_base.strftime("%Y-%m-%d")

    bloqueio = obter_bloqueio_aulas(cursor, data_agendamento)
    if aula_bloqueada_por_horario(aula, bloqueio):
        conn.close()
        return render_template(
            "mensagem.html",
            titulo="Aula bloqueada",
            mensagem="A academia tera fechamento especial neste dia. As aulas a partir deste horario nao estao disponiveis para agendamento."
        )

    # vagas ocupadas
    cursor.execute("""
        SELECT COUNT(*) AS total
        FROM agendamentos
        WHERE aula_id = %s AND data_agendamento = %s
    """, (aula_id, data_agendamento))
    ocupadas = cursor.fetchone()["total"]

    cursor.execute("""
    SELECT COUNT(*) AS total
    FROM agendamentos
    WHERE aluno_id = %s
""", (aluno_id,))

    aulas_usadas_sistema = cursor.fetchone()["total"]
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
        return redirect(url_for("cronograma"))
    
    if not aluno["aceitou_contrato"]:
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

    cursor.execute("""
        UPDATE alunos
        SET aceitou_contrato = TRUE,
            data_aceite_contrato = %s
        WHERE id = %s
    """, (
        (datetime.utcnow() - timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S"),
        aluno_id
    ))

    data_base = obter_data_base()
    data_agendamento = data_base.strftime("%Y-%m-%d")

    cursor.execute("SELECT * FROM aulas WHERE id = %s", (aula_id,))
    aula = cursor.fetchone()

    bloqueio = obter_bloqueio_aulas(cursor, data_agendamento)
    if aula and aula_bloqueada_por_horario(aula, bloqueio):
        conn.close()
        session.pop("aluno_pendente_contrato", None)
        session.pop("aula_pendente_contrato", None)
        return render_template(
            "mensagem.html",
            titulo="Aula bloqueada",
            mensagem="A academia tera fechamento especial neste dia. As aulas a partir deste horario nao estao disponiveis para agendamento."
        )

    cursor.execute("""
        INSERT INTO agendamentos (aluno_id, aula_id, data_agendamento)
        VALUES (%s, %s, %s)
        ON CONFLICT DO NOTHING
    """, (aluno_id, aula_id, data_agendamento))

    conn.commit()

    cursor.execute("SELECT * FROM alunos WHERE id = %s", (aluno_id,))
    aluno = cursor.fetchone()

    cursor.execute("""
        SELECT COUNT(*) AS total
        FROM agendamentos
        WHERE aluno_id = %s
    """, (aluno_id,))

    aulas_usadas_sistema = cursor.fetchone()["total"]

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

    return redirect(url_for("cronograma"))

init_db()

if __name__ == "__main__":
    app.run(debug=True)
