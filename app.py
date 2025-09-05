from flask import Flask, render_template, request, redirect, url_for, session, flash
from pymongo import MongoClient
import bcrypt
from datetime import datetime
import os
from bson import ObjectId
from utils import generate_chart
import certifi

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "e5a6f0b8c2d94d8b9b23a6f3e7c4129a5c1d7e8f9a4b0c3d5f6a8b9c7e2d4f1a")

# Initialize as None
db = None
users = None
salary_slips = None
expenses = None

try:
    client = MongoClient(
        'Paste your mongodb atlas uri',
        tls=True,
        tlsCAFile=certifi.where(),
        serverSelectionTimeoutMS=30000,
        connectTimeoutMS=30000,
        socketTimeoutMS=30000,
        retryWrites=True
    )
    # Ping to confirm connection
    client.admin.command('ping')
    print("✅ MongoDB Atlas connected successfully")

    # ONLY now assign database and collections
    db = client['Payroll']
    users = db['userdata']
    salary_slips = db['salary_slips']
    expenses = db['expenses']

except Exception as e:
    print(f"❌ MongoDB Atlas connection failed: {e}")
    # Already None, so no need to reassign
    pass


@app.route("/")
def index():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form["name"]
        email = request.form["email"]
        role = request.form["role"]
        password = request.form["password"].encode("utf-8")
        hashed = bcrypt.hashpw(password, bcrypt.gensalt())

        if users is None:
            flash("Database not connected!", "danger")
            return redirect(url_for("register"))

        if users.find_one({"email": email}):
            flash("Email already exists!", "warning")
            return redirect(url_for("register"))

        result = users.insert_one({
            "name": name,
            "email": email,
            "role": role,
            "password": hashed
        })
        print(f"✅ User registered with ID: {result.inserted_id}")
        flash("Registration successful! Please login.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"].encode("utf-8")

        if users is None:
            flash("Database not connected!", "danger")
            return redirect(url_for("login"))

        user = users.find_one({"email": email})
        if not user:
            flash("User not found!", "danger")
            return redirect(url_for("login"))

        if bcrypt.checkpw(password, user["password"]):
            session["user_id"] = str(user["_id"])
            session["role"] = user["role"]
            session["name"] = user["name"]
            flash("Logged in successfully!", "success")
            return redirect(url_for("dashboard"))
        else:
            flash("Invalid credentials!", "danger")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out.", "info")
    return redirect(url_for("login"))


@app.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        return redirect(url_for("login"))

    user_id = session["user_id"]
    role = session["role"]

    # Check if collections are available
    if users is None or salary_slips is None or expenses is None:
        flash("Database connection is not available.", "danger")
        return render_template(
            "dashboard.html",
            role=role,
            employees=[],
            salary_slips=[],
            salary_chart=None,
            expense_chart=None,
            expenses=[],
        )

    if role == "admin":
        try:
            employees = list(users.find({"role": "employee"}))
            employee_names = {str(emp["_id"]): emp["name"] for emp in employees}

            slips = list(salary_slips.find().sort("generated_at", -1).limit(10))
            for slip in slips:
                emp_id = slip.get("employee_id")
                slip["employee_name"] = employee_names.get(str(emp_id), "Unknown") if emp_id else "Unknown"

            return render_template(
                "dashboard.html",
                role=role,
                employees=employees,
                salary_slips=slips
            )
        except Exception as e:
            flash("Error loading admin data.", "danger")
            return redirect(url_for("dashboard"))

    elif role == "employee":
        try:
            salary_hist = list(salary_slips.find({"employee_id": user_id}))
            salary_labels = [s["month"] for s in salary_hist]
            salary_values = [s["net_salary"] for s in salary_hist]
            salary_chart = generate_chart(salary_labels, salary_values, "Monthly Salary")

            expense_hist = list(expenses.find({"employee_id": user_id}))
            expense_labels = [e["month"] for e in expense_hist]
            expense_values = [e["amount"] for e in expense_hist]
            expense_chart = (
                generate_chart(expense_labels, expense_values, "Monthly Expenses")
                if expense_values else None
            )

            return render_template(
                "dashboard.html",
                role=role,
                salary_chart=salary_chart,
                expense_chart=expense_chart,
                expenses=expense_hist
            )
        except Exception as e:
            flash("Error loading your data.", "danger")
            return redirect(url_for("dashboard"))

    flash("Invalid role.", "danger")
    return redirect(url_for("logout"))


@app.route("/generate_slip", methods=["POST"])
def generate_slip():
    if session.get("role") != "admin":
        return redirect(url_for("dashboard"))

    if users is None or salary_slips is None:
        flash("Database is not available. Cannot generate salary slip.", "danger")
        return redirect(url_for("dashboard"))

    emp_id = request.form["employee_id"]
    month = request.form["month"]

    try:
        basic = float(request.form["basic"])
        bonus = float(request.form.get("bonus", 0))
        deductions = float(request.form.get("deductions", 0))
    except (ValueError, TypeError):
        flash("Invalid number format for salary fields.", "danger")
        return redirect(url_for("dashboard"))

    net_salary = basic + bonus - deductions

    try:
        salary_slips.update_one(
            {"employee_id": emp_id, "month": month},
            {
                "$set": {
                    "employee_id": emp_id,
                    "month": month,
                    "basic": basic,
                    "bonus": bonus,
                    "deductions": deductions,
                    "net_salary": net_salary,
                    "generated_at": datetime.utcnow(),
                }
            },
            upsert=True,
        )
        flash(f"Salary slip generated for {month}.", "success")
    except Exception as e:
        flash("Failed to save salary slip. Try again.", "danger")
        print(f"Error saving salary slip: {e}")

    return redirect(url_for("dashboard"))


@app.route("/submit_expense", methods=["POST"])
def submit_expense():
    if session.get("role") != "employee":
        return redirect(url_for("dashboard"))

    if expenses is None:
        flash("Database not connected!", "danger")
        return redirect(url_for("dashboard"))

    user_id = session["user_id"]
    month = request.form["month"]

    try:
        amount = float(request.form["amount"])
    except (ValueError, TypeError):
        flash("Invalid amount format.", "danger")
        return redirect(url_for("dashboard"))

    category = request.form["category"]
    description = request.form.get("description", "")

    try:
        expenses.update_one(
            {"employee_id": user_id, "month": month},
            {
                "$set": {
                    "employee_id": user_id,
                    "month": month,
                    "amount": amount,
                    "category": category,
                    "description": description,
                    "submitted_at": datetime.utcnow(),
                }
            },
            upsert=True,
        )
        flash("Expense submitted successfully.", "success")
    except Exception as e:
        flash("Failed to submit expense.", "danger")
        print(f"Error submitting expense: {e}")

    return redirect(url_for("dashboard"))

@app.route("/admin/salary")
def admin_salary():
    if session.get("role") != "admin":
        return redirect(url_for("dashboard"))

    if users is None:
        flash("Database not available.", "danger")
        return render_template("admin_salary.html", employees=[])

    try:
        employees = list(users.find({"role": "employee"}))
    except Exception as e:
        flash("Could not load employees.", "danger")
        employees = []

    return render_template("admin_salary.html", employees=employees)


@app.route("/employee/expense")
def employee_expense():
    if session.get("role") != "employee":
        return redirect(url_for("dashboard"))
    return render_template("employee_expense.html")

@app.errorhandler(404)
def not_found(e):
    return "404 - Page not found", 404


@app.errorhandler(500)
def server_error(e):
    return "500 - Internal server error", 500


if __name__ == "__main__":

    app.run(host='0.0.0.0',debug=True)


