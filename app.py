from flask import Flask, render_template, request, redirect, url_for, session
import sqlite3
import pandas as pd
import unicodedata
from datetime import datetime

app = Flask(__name__)
app.secret_key = "academia_secret"

DB_NAME = "academia.db"


def conectar():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def remover_acentos(texto):
    return unicodedata.normalize('NFKD', texto).encode('ASCII', 'ignore').decode('ASCII')


def init_db():
    conn = conectar()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS alunos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT,
            telefone TEXT,
            plano TEXT,
            vencimento TEXT,
            status_pagamento TEXT,
            observacao TEXT,
            aulas_restantes INTEGER DEFAULT 12,
            usuario TEXT,
            senha TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS aulas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dia_semana TEXT,
            horario TEXT,
            modalidade TEXT,
            capacidade INTEGER DEFAULT 10
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS agendamentos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            aluno_id INTEGER,
            aula_id INTEGER,
            data_agendamento TEXT,
            UNIQUE(aluno_id, aula_id, data_agendamento)
        )
    """)

    conn.commit()

    total_aulas = cursor.execute("SELECT COUNT(*) FROM aulas").fetchone()[0]
    if total_aulas == 0:
        aulas_padrao = [
            ("Segunda-feira", "07:00", "Neopilates", 10),
            ("Segunda-feira", "08:00", "Acroyoga", 10),
            ("Segunda-feira", "09:00", "Neopilates", 10),
            ("Segunda-feira", "16:00", "Neopilates", 10),
            ("Segunda-feira", "17:00", "Acroyoga", 10),
            ("Segunda-feira", "18:00", "Dance Fit", 10),
            ("Terça-feira", "05:00", "Neopilates", 10),
            ("Terça-feira", "07:00", "Circo / Spin Fit", 10),
            ("Terça-feira", "08:00", "Work HIIT", 10),
            ("Terça-feira", "09:00", "NeoKids", 10),
            ("Terça-feira", "16:00", "NeoKids", 10),
            ("Terça-feira", "18:00", "Neopilates / Spin Fit", 10),
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
            VALUES (?, ?, ?, ?)
        """, aulas_padrao)
        conn.commit()

    conn.close()


def obter_dia_semana():
    mapa = {
        0: "Segunda-feira",
        1: "Terça-feira",
        2: "Quarta-feira",
        3: "Quinta-feira",
        4: "Sexta-feira",
        5: "Sábado",
        6: "Domingo",
    }
    return mapa[datetime.now().weekday()]


def listar_aulas_do_dia(dia_semana=None):
    if not dia_semana:
        dia_semana = obter_dia_semana()

    conn = conectar()
    aulas = conn.execute("""
        SELECT a.id, a.dia_semana, a.horario, a.modalidade, a.capacidade,
               COUNT(ag.id) AS ocupadas
        FROM aulas a
        LEFT JOIN agendamentos ag ON ag.aula_id = a.id
        GROUP BY a.id
        HAVING a.dia_semana = ?
        ORDER BY a.horario
    """, (dia_semana,)).fetchall()
    conn.close()

    dados = []
    for aula in aulas:
        ocupadas = aula["ocupadas"] or 0
        capacidade = aula["capacidade"] or 10
        restantes = max(capacidade - ocupadas, 0)
        percentual = int((ocupadas / capacidade) * 100) if capacidade else 0
        item = dict(aula)
        item["ocupadas"] = ocupadas
        item["restantes"] = restantes
        item["percentual"] = percentual
        item["lotada"] = ocupadas >= capacidade
        dados.append(item)
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
        erro = "Usuário ou senha inválidos"
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
    total = cursor.execute("SELECT COUNT(*) FROM alunos").fetchone()[0]
    pagos = cursor.execute("SELECT COUNT(*) FROM alunos WHERE status_pagamento = 'Pago'").fetchone()[0]
    pendentes = cursor.execute("SELECT COUNT(*) FROM alunos WHERE status_pagamento = 'Pendente'").fetchone()[0]
    atrasados = cursor.execute("SELECT COUNT(*) FROM alunos WHERE status_pagamento = 'Atrasado'").fetchone()[0]
    alunos = cursor.execute("SELECT * FROM alunos ORDER BY nome ASC").fetchall()
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
    if busca:
        alunos = conn.execute(
            "SELECT * FROM alunos WHERE nome LIKE ? ORDER BY nome ASC",
            (f"%{busca}%",)
        ).fetchall()
    else:
        alunos = conn.execute("SELECT * FROM alunos ORDER BY nome ASC").fetchall()
    conn.close()
    return render_template("alunos.html", alunos=alunos, busca=busca)


@app.route("/novo_aluno", methods=["GET", "POST"])
def novo_aluno():
    if "admin_logado" not in session:
        return redirect(url_for("login"))

    if request.method == "POST":
        nome = request.form["nome"]
        usuario = remover_acentos(nome.split()[0].lower())

        conn = conectar()
        conn.execute("""
            INSERT INTO alunos (nome, telefone, plano, vencimento, status_pagamento, observacao, aulas_restantes, usuario, senha)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            nome,
            request.form["telefone"],
            request.form["plano"],
            request.form["vencimento"],
            request.form["status_pagamento"],
            request.form.get("observacao", ""),
            12,
            usuario,
            "1234"
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
    if request.method == "POST":
        conn.execute("""
            UPDATE alunos
            SET nome = ?, telefone = ?, plano = ?, vencimento = ?, status_pagamento = ?, observacao = ?
            WHERE id = ?
        """, (
            request.form["nome"],
            request.form["telefone"],
            request.form["plano"],
            request.form["vencimento"],
            request.form["status_pagamento"],
            request.form.get("observacao", ""),
            id
        ))
        conn.commit()
        conn.close()
        return redirect(url_for("alunos"))

    aluno = conn.execute("SELECT * FROM alunos WHERE id = ?", (id,)).fetchone()
    conn.close()
    return render_template("editar_aluno.html", aluno=aluno)


@app.route("/excluir_aluno/<int:id>")
def excluir_aluno(id):
    if "admin_logado" not in session:
        return redirect(url_for("login"))

    conn = conectar()
    conn.execute("DELETE FROM alunos WHERE id = ?", (id,))
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
                        INSERT INTO alunos (nome, telefone, plano, vencimento, status_pagamento, observacao, aulas_restantes, usuario, senha)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        nome,
                        str(row.get("Telefone", "")),
                        str(row.get("Plano", "")),
                        str(row.get("Vencimento", "")),
                        str(row.get("Status", "Pendente")),
                        "",
                        12,
                        usuario,
                        "1234"
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
    alunos = conn.execute("SELECT * FROM alunos ORDER BY nome ASC").fetchall()
    conn.close()

    return render_template(
        "cronograma.html",
        dia_atual=dia_atual,
        aulas_hoje=aulas_hoje,
        alunos=alunos
    )


@app.route("/agendar_aula/<int:aula_id>", methods=["POST"])
def agendar_aula(aula_id):
    aluno_id = request.form["aluno_id"]

    conn = conectar()
    cursor = conn.cursor()

    aluno = cursor.execute("SELECT * FROM alunos WHERE id = ?", (aluno_id,)).fetchone()
    aula = cursor.execute("SELECT * FROM aulas WHERE id = ?", (aula_id,)).fetchone()
    ocupadas = cursor.execute("SELECT COUNT(*) FROM agendamentos WHERE aula_id = ?", (aula_id,)).fetchone()[0]

    if not aluno or not aula:
        conn.close()
        return redirect(url_for("cronograma"))

    if aluno["aulas_restantes"] <= 0:
        conn.close()
        return redirect(url_for("cronograma"))

    if ocupadas >= aula["capacidade"]:
        conn.close()
        return redirect(url_for("cronograma"))

    data_agendamento = datetime.now().strftime("%Y-%m-%d")
    ja_agendado = cursor.execute("""
        SELECT 1 FROM agendamentos
        WHERE aluno_id = ? AND aula_id = ? AND data_agendamento = ?
    """, (aluno_id, aula_id, data_agendamento)).fetchone()

    if ja_agendado:
        conn.close()
        return redirect(url_for("cronograma"))

    cursor.execute("""
        INSERT INTO agendamentos (aluno_id, aula_id, data_agendamento)
        VALUES (?, ?, ?)
    """, (aluno_id, aula_id, data_agendamento))

    cursor.execute("""
        UPDATE alunos
        SET aulas_restantes = aulas_restantes - 1
        WHERE id = ?
    """, (aluno_id,))

    conn.commit()
    conn.close()

    return render_template("agendamento_sucesso.html")


init_db()

if __name__ == "__main__":
    app.run(debug=True)