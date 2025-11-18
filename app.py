from flask import Flask, render_template, request, redirect, send_file, session
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import os
import csv
from openpyxl import Workbook
from sqlalchemy import text

app = Flask(__name__)
app.secret_key = "super_secret_key"

# ---------------------------------------------------------
# Railway PostgreSQL 設定
# ---------------------------------------------------------
raw_url = os.getenv("DATABASE_URL")

if raw_url:
    # Railway 給的是 postgres:// → SQLAlchemy 要 postgresql+psycopg2://
    if raw_url.startswith("postgres://"):
        raw_url = raw_url.replace("postgres://", "postgresql+psycopg2://", 1)
    app.config["SQLALCHEMY_DATABASE_URI"] = raw_url
else:
    # 本機開發時可用以下方式（若未安裝本機 PostgreSQL 可自行改成 SQLite）
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///local.db"

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

# ---------------------------------------------------------
# 使用者資料表
# ---------------------------------------------------------
class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True)
    password_hash = db.Column(db.String(200))
    employee_id = db.Column(db.String(50))
    role = db.Column(db.String(20), default="user")  # user / admin

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

# ---------------------------------------------------------
# 客戶資料表
# ---------------------------------------------------------
class Client(db.Model):
    __tablename__ = "customers"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50))
    house_address = db.Column(db.String(200))
    register_address = db.Column(db.String(200))
    first_contact = db.Column(db.DateTime)
    next_follow = db.Column(db.DateTime)
    notes = db.Column(db.Text)
    user_id = db.Column(db.Integer)

# ---------------------------------------------------------
# 建立資料表 (Railway 必須在 app context 下進行)
# ---------------------------------------------------------
with app.app_context():
    db.create_all()
    try:
        db.session.execute(text("SELECT 1"))
        print("🔥 PostgreSQL 連線成功！")
    except Exception as e:
        print("❌ PostgreSQL 連線失敗：", e)

# ---------------------------------------------------------
# 登入保護
# ---------------------------------------------------------
def login_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return redirect("/login")
        return func(*args, **kwargs)
    return wrapper

# ---------------------------------------------------------
# 登入頁
# ---------------------------------------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            session["user_id"] = user.id
            session["username"] = user.username
            session["employee_id"] = user.employee_id
            session["role"] = user.role
            return redirect("/list")

        return render_template("login.html", error="帳號或密碼錯誤")

    return render_template("login.html")

# ---------------------------------------------------------
# 登出
# ---------------------------------------------------------
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

# ---------------------------------------------------------
# 首頁
# ---------------------------------------------------------
@app.route("/")
def home():
    return redirect("/list") if "user_id" in session else redirect("/login")

# ---------------------------------------------------------
# 新增客戶
# ---------------------------------------------------------
@app.route("/add", methods=["GET", "POST"])
@login_required
def add_client():
    if request.method == "POST":
        name = request.form["name"]
        house_address = request.form["house_address"]
        register_address = request.form["register_address"]
        notes = request.form["notes"]

        now = datetime.now()

        chosen_next = request.form["next_follow"].strip()
        next_time = now + timedelta(days=14) if chosen_next == "" else datetime.strptime(chosen_next, "%Y/%m/%d")

        if house_address.strip() == register_address.strip():
            register_address = "同左"

        c = Client(
            name=name,
            house_address=house_address,
            register_address=register_address,
            first_contact=now,
            next_follow=next_time,
            notes=notes,
            user_id=session["user_id"]
        )

        db.session.add(c)
        db.session.commit()
        return redirect("/list")

    return render_template("add.html")

# ---------------------------------------------------------
# 編輯客戶
# ---------------------------------------------------------
@app.route("/edit/<int:id>", methods=["GET", "POST"])
@login_required
def edit_client(id):
    client = Client.query.get(id)

    if session["role"] != "admin" and client.user_id != session["user_id"]:
        return "⛔ 你沒有權限編輯這筆資料"

    if request.method == "POST":
        client.name = request.form["name"]
        client.house_address = request.form["house_address"]
        client.register_address = request.form["register_address"]
        client.notes = request.form["notes"]

        chosen_next = request.form["next_follow"].strip()
        if chosen_next:
            client.next_follow = datetime.strptime(chosen_next, "%Y/%m/%d")

        if client.house_address.strip() == client.register_address.strip():
            client.register_address = "同左"

        db.session.commit()
        return redirect("/list")

    return render_template("edit.html", client=client)

# ---------------------------------------------------------
# 刪除客戶
# ---------------------------------------------------------
@app.route("/delete/<int:id>")
@login_required
def delete_client(id):
    c = Client.query.get(id)

    if session["role"] != "admin" and c.user_id != session["user_id"]:
        return "⛔ 你沒有權限刪除這筆資料"

    db.session.delete(c)
    db.session.commit()
    return redirect("/list")

# ---------------------------------------------------------
# 客戶列表
# ---------------------------------------------------------
@app.route("/list")
@login_required
def list_clients():
    search = request.args.get("q", "").strip()
    today_flag = request.args.get("today", "") == "1"
    today_str = datetime.now().strftime("%Y-%m-%d")

    role = session.get("role")
    user_id = session.get("user_id")

    if role == "admin":
        query = Client.query
    else:
        query = Client.query.filter_by(user_id=user_id)

    if search:
        keyword = f"%{search}%"
        query = query.filter(
            (Client.name.like(keyword)) |
            (Client.house_address.like(keyword)) |
            (Client.register_address.like(keyword)) |
            (Client.notes.like(keyword))
        )

    clients = query.all()

    if today_flag:
        clients = [c for c in clients if c.next_follow.strftime("%Y-%m-%d") == today_str]

    today_count = sum(
        1 for c in (Client.query.all() if role == "admin" else Client.query.filter_by(user_id=user_id).all())
        if c.next_follow.strftime("%Y-%m-%d") == today_str
    )

    return render_template("list.html",
        clients=clients, search=search,
        today_flag=today_flag, today_str=today_str, today_count=today_count)

# ---------------------------------------------------------
# 匯出 CSV
# ---------------------------------------------------------
@app.route("/export_csv")
@login_required
def export_csv():
    role = session["role"]
    user_id = session["user_id"]

    filename = "clients_export.csv"

    data = Client.query.all() if role == "admin" else Client.query.filter_by(user_id=user_id).all()

    with open(filename, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["客戶姓名", "房屋地址", "戶籍地址", "第一次開發", "下次跟進", "備註"])

        for c in data:
            writer.writerow([
                c.name,
                c.house_address,
                c.register_address,
                c.first_contact.strftime("%Y-%m-%d %H:%M"),
                c.next_follow.strftime("%Y-%m-%d"),
                c.notes
            ])

    return send_file(filename, as_attachment=True)

# ---------------------------------------------------------
# 匯出 Excel
# ---------------------------------------------------------
@app.route("/export_excel")
@login_required
def export_excel():
    role = session["role"]
    user_id = session["user_id"]

    filename = "clients_export.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "客戶資料"

    ws.append(["客戶姓名", "房屋地址", "戶籍地址", "第一次開發", "下次跟進", "備註"])

    data = Client.query.all() if role == "admin" else Client.query.filter_by(user_id=user_id).all()

    for c in data:
        ws.append([
            c.name,
            c.house_address,
            c.register_address,
            c.first_contact.strftime("%Y-%m-%d %H:%M"),
            c.next_follow.strftime("%Y-%m-%d"),
            c.notes
        ])

    wb.save(filename)
    return send_file(filename, as_attachment=True)

# ---------------------------------------------------------
# 建立管理員帳號
# ---------------------------------------------------------
@app.route("/create_admin")
def create_admin():
    admin = User.query.filter_by(username="admin").first()
    if admin:
        return "管理員已存在！"

    admin = User(
        username="admin",
        employee_id="A000",
        role="admin"
    )
    admin.set_password("123456")

    db.session.add(admin)
    db.session.commit()
    return "管理員帳號已建立： admin / 123456"

# ---------------------------------------------------------
# 員工管理
# ---------------------------------------------------------
@app.route("/users")
@login_required
def user_list():
    if session["role"] != "admin":
        return "⛔ 只有管理員可以查看員工列表"

    users = User.query.all()
    return render_template("users.html", users=users)

@app.route("/users/add", methods=["GET", "POST"])
@login_required
def add_user():
    if session["role"] != "admin":
        return "⛔ 只有管理員可以新增員工"

    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        employee_id = request.form["employee_id"]
        role = request.form["role"]

        if User.query.filter_by(username=username).first():
            return render_template("user_add.html", error="此帳號已存在")

        user = User(
            username=username,
            employee_id=employee_id,
            role=role
        )
        user.set_password(password)

        db.session.add(user)
        db.session.commit()

        return redirect("/users")

    return render_template("user_add.html")

@app.route("/users/edit/<int:id>", methods=["GET", "POST"])
@login_required
def edit_user(id):
    if session["role"] != "admin":
        return "⛔ 只有管理員可以編輯員工"

    user = User.query.get(id)

    if request.method == "POST":
        user.username = request.form["username"]
        user.employee_id = request.form["employee_id"]
        user.role = request.form["role"]

        new_pass = request.form["password"].strip()
        if new_pass:
            user.set_password(new_pass)

        db.session.commit()
        return redirect("/users")

    return render_template("user_edit.html", user=user)

@app.route("/users/delete/<int:id>")
@login_required
def delete_user(id):
    if session["role"] != "admin":
        return "⛔ 只有管理員可以刪除員工"

    if id == session["user_id"]:
        return "⛔ 無法刪除自己"

    user = User.query.get(id)
    db.session.delete(user)
    db.session.commit()

    return redirect("/users")

# ---------------------------------------------------------
# Flask 啟動
# ---------------------------------------------------------
if __name__ == "__main__":
    app.run(debug=True)
