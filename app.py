from flask import Flask, render_template, request, redirect, url_for, session
import os
import psycopg2
from psycopg2.extras import RealDictCursor
import pandas as pd
import unicodedata
from datetime import datetime, date

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
            data_nascimento TEXT
        )
    """)

    cursor.execute("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'alunos' AND column_name = 'data_nascimento'
    """)
    coluna = cursor.fetchone()
    if not coluna:
        cursor.execute("ALTER TABLE alunos ADD COLUMN data_nascimento TEXT")

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

    conn.commit()

    cursor.execute("SELECT COUNT(*) AS total FROM aulas")
    total_aulas = cursor.fetchone()["total"]

    if total_aulas == 0:
        aulas_padrao = [
            ("Segunda-feira", "07:00", "Neopilates", 10),
            ("Segunda-feira", "08:00", "Acroyoga", 10),
            ("Segunda-feira", "09:00", "Neopilates", 10),
            ("Segunda-feira", "16:00", "Neopilates", 10),
            ("Segunda-feira", "17:00", "Acroyoga", 10),
            ("Segunda-feira", "18:00", "Dance Fit", 10),
            ("Terca-feira", "05:00", "Neopilates", 10),
            ("Terca-feira", "07:00", "Circo / Spin Fit", 10),
            ("Terca-feira", "08:00", "Work HIIT", 10),
            ("Terca-feira", "09:00", "NeoKids", 10),
            ("Terca-feira", "16:00", "NeoKids", 10),
            ("Terca-feira", "18:00", "Neopilates / Spin Fit", 10),
            ("Quarta-feira", "07:00", "Neopilates", 10),
            ("Quarta-feira", "08:00", "Flex Fit", 10),
            ("Quarta-feira", "09:00", "Cross Fight", 10),
            ("Quarta-feira", "16:00", "Neopilates", 10),
            ("Quarta-feira", "17:00", "Acroyoga", 10),
            ("Quarta-feira", "18:00", "Dance Fit / C.Fight", 10),
            ("Quinta-feira", "05:00", "Neopilates", 10),
            ("Quinta-feira", "07:00", "Circo / Spin Fit", 10),
            ("Quinta-feira", "08:00", "Work HIIT", 10),
            ("Quinta-feira", "09:00", "NeoKids", 10),
            ("Quinta-feira", "16:00", "NeoKids", 10),
            ("Quinta-feira", "18:00", "Neopilates / Spin Fit", 10),
            ("Sexta-feira", "07:00", "Flex Fit", 10),
            ("Sexta-feira", "08:00", "Acroyoga", 10),
            ("Sexta-feira", "17:00", "Cross Fight", 10),
            ("Sexta-feira", "18:00", "Spin Fit", 10),
        ]

        cursor.executemany("""
            INSERT INTO aulas (dia_semana, horario, modalidade, capacidade)
            VALUES (%s, %s, %s, %s)
        """, aulas_padrao)

        conn.commit()

    conn.close()


def obter_dia_semana():
    mapa = {
        0: "Segunda-feira",
        1: "Terca-feira",
        2: "Quarta-feira",
        3: "Quinta-feira",
        4: "Sexta-feira",
        5: "Sabado",
        6: "Domingo",
    }
    return mapa[datetime.now().weekday()]


def listar_aulas_do_dia(dia_semana=None):
    if not dia_semana:
        dia_semana = obter_dia_semana()

    conn = conectar()
    cursor = conn.cursor()
    hoje = datetime.now().strftime("%Y-%m-%d")

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

    dados = []
    for aula in aulas:
        ocupadas = aula["ocupadas"] or 0
        capacidade = aula["capacidade"] or 10

        cursor.execute("""
            SELECT al.nome, al.data_nascimento
            FROM agendamentos ag
            JOIN alunos al ON al.id = ag.aluno_id
            WHERE ag.aula_id = %s AND ag.data_agendamento = %s
            ORDER BY al.nome ASC
        """, (aula["id"], hoje))
        inscritos_db = cursor.fetchall()

        inscritos = [
            {
                "nome": i["nome"],
                "idade": calcular_idade(i["data_nascimento"])
            }
            for i in inscritos_db
        ]

        item = dict(aula)
        item["restantes"] = max(capacidade - ocupadas, 0)
        item["percentual"] = int((ocupadas / capacidade) * 100) if capacidade else 0
        item["lotada"] = ocupadas >= capacidade
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
        if request.form["usuario"] == "admin" and request.form["senha"] == "1234":
            session["admin_logado"] = True
            return redirect(url_for("dashboard"))
        erro = "Usuario ou senha invalidos"
    return render_template("login.html", erro=erro)


@app.route("/logout")
def logout():
    session.pop("admin_logado", None)
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
        aulas_hoje=aulas_hoje
    )


@app.route("/alunos")
def alunos():
    if "admin_logado" not in session:
        return redirect(url_for("login"))

    busca = request.args.get("busca", "").strip()
    conn = conectar()
    cursor = conn.cursor()

    if busca:
        cursor.execute("SELECT * FROM alunos WHERE nome ILIKE %s ORDER BY nome ASC", (f"%{busca}%",))
        alunos = cursor.fetchall()
    else:
        cursor.execute("SELECT * FROM alunos ORDER BY nome ASC")
        alunos = cursor.fetchall()

    conn.close()
    return render_template("alunos.html", alunos=alunos, busca=busca, calcular_idade=calcular_idade)


@app.route("/novo_aluno", methods=["GET", "POST"])
def novo_aluno():
    if "admin_logado" not in session:
        return redirect(url_for("login"))

    if request.method == "POST":
        nome = request.form["nome"]
        usuario = remover_acentos(nome.split()[0].lower())

        conn = conectar()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO alunos (
                nome, telefone, plano, vencimento, status_pagamento,
                observacao, aulas_restantes, usuario, senha, data_nascimento
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            nome,
            request.form["telefone"],
            request.form["plano"],
            request.form["vencimento"],
            request.form["status_pagamento"],
            request.form.get("observacao", ""),
            12,
            usuario,
            "1234",
            request.form.get("data_nascimento", "")
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
        cursor.execute("""
            UPDATE alunos
            SET nome=%s, telefone=%s, plano=%s, vencimento=%s,
                status_pagamento=%s, observacao=%s, data_nascimento=%s
            WHERE id=%s
        """, (
            request.form["nome"],
            request.form["telefone"],
            request.form["plano"],
            request.form["vencimento"],
            request.form["status_pagamento"],
            request.form.get("observacao", ""),
            request.form.get("data_nascimento", ""),
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
                df = pd.read_excel(arquivo)
                conn = conectar()
                cursor = conn.cursor()

                for _, row in df.iterrows():
                    nome = str(row.get("Nome", "")).strip()
                    if not nome:
                        continue

                    usuario = remover_acentos(nome.split()[0].lower())

                    cursor.execute("""
                        INSERT INTO alunos (
                            nome, telefone, plano, vencimento, status_pagamento,
                            observacao, aulas_restantes, usuario, senha, data_nascimento
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        nome,
                        str(row.get("Telefone", "")),
                        str(row.get("Plano", "")),
                        str(row.get("Vencimento", "")),
                        str(row.get("Status", "Pendente")),
                        "",
                        12,
                        usuario,
                        "1234",
                        str(row.get("DataNascimento", ""))
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

    conn = conectar()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM alunos ORDER BY nome ASC")
    alunos = cursor.fetchall()
    conn.close()

    return render_template("cronograma.html", dia_atual=dia_atual, aulas_hoje=aulas_hoje, alunos=alunos)


@app.route("/agendar_aula/<int:aula_id>", methods=["POST"])
def agendar_aula(aula_id):
    aluno_id = request.form["aluno_id"]
    conn = conectar()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM alunos WHERE id = %s", (aluno_id,))
    aluno = cursor.fetchone()

    cursor.execute("SELECT * FROM aulas WHERE id = %s", (aula_id,))
    aula = cursor.fetchone()

    data_agendamento = datetime.now().strftime("%Y-%m-%d")

    cursor.execute(
        "SELECT COUNT(*) AS total FROM agendamentos WHERE aula_id = %s AND data_agendamento = %s",
        (aula_id, data_agendamento)
    )
    ocupadas = cursor.fetchone()["total"]

    if not aluno or not aula or aluno["aulas_restantes"] <= 0 or ocupadas >= aula["capacidade"]:
        conn.close()
        return redirect(url_for("cronograma"))

    cursor.execute("""
        SELECT 1 AS existe
        FROM agendamentos
        WHERE aluno_id = %s AND aula_id = %s AND data_agendamento = %s
    """, (aluno_id, aula_id, data_agendamento))
    ja_agendado = cursor.fetchone()

    if ja_agendado:
        conn.close()
        return redirect(url_for("cronograma"))

    cursor.execute(
        "INSERT INTO agendamentos (aluno_id, aula_id, data_agendamento) VALUES (%s, %s, %s)",
        (aluno_id, aula_id, data_agendamento)
    )

    cursor.execute(
        "UPDATE alunos SET aulas_restantes = aulas_restantes - 1 WHERE id = %s",
        (aluno_id,)
    )

    conn.commit()
    conn.close()
    return render_template("agendamento_sucesso.html")


@app.route("/acesso_professor", methods=["POST"])
def acesso_professor():
    senha = request.form.get("senha_professor", "")
    if senha == "prof123":
        session["professor_liberado"] = True
    return redirect(url_for("cronograma"))


@app.route("/sair_professor")
def sair_professor():
    session.pop("professor_liberado", None)
    return redirect(url_for("cronograma"))


init_db()

if __name__ == "__main__":
    app.run(debug=True)
