from flask import Flask, render_template, request, redirect, session, flash
import sqlite3
from datetime import datetime, timedelta
import cv2
import os
import hashlib
import random
import string
from face_engine import capture_face_images, verify_face, verify_face_auto

app = Flask(__name__)
app.secret_key = os.environ.get("ATTENDIFY_SECRET", hashlib.sha256(os.urandom(32)).hexdigest())

# Database helper functions
def get_db():
    conn = sqlite3.connect("attendance.db", timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    return conn

def close_db(conn):
    if conn:
        try:
            conn.close()
        except:
            pass

# Email configuration
SMTP_SERVER = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_EMAIL = os.environ.get("SMTP_EMAIL", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")

# Simple password hashing
def hash_password(password):
    salt = os.environ.get("ATTENDIFY_SALT", "attendify_default_salt")
    return hashlib.sha256((password + salt).encode()).hexdigest()

# Generate OTP
def generate_otp(length=6):
    return ''.join(random.choices(string.digits, k=length))

# Send OTP email
def send_otp_email(email, otp):
    if not SMTP_EMAIL:
        print(f"Email not configured. OTP for {email}: {otp}")
        return True
    
    try:
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        
        msg = MIMEMultipart()
        msg['From'] = SMTP_EMAIL
        msg['To'] = email
        msg['Subject'] = 'Verify your email - Attendify OTP'
        
        body = f'''
<h2>Your Attendify Verification Code</h2>
<p>Your OTP is: <strong>{otp}</strong></p>
<p>This code expires in 10 minutes.</p>
<p>If you didn't request this, please ignore this email.</p>
'''
        msg.attach(MIMEText(body, 'html'))
        
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_EMAIL, SMTP_PASSWORD)
            server.sendmail(SMTP_EMAIL, email, msg.as_string())
        
        return True
    except Exception as e:
        print(f"Email error: {e}")
        return False

# Create faces folder
import os
os.makedirs("static/faces", exist_ok=True)

# Initialize database on startup
def init_db():
    conn = sqlite3.connect("attendance.db", timeout=10)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            email TEXT UNIQUE,
            password TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            email TEXT,
            face_encoding BLOB
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER,
            date TEXT,
            time TEXT
        )
    """)
    # OTP verification table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS otp_verify (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT,
            otp TEXT,
            expires_at TEXT,
            used INTEGER DEFAULT 0
        )
    """)
    # Classes table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS classes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            schedule TEXT,
            created_at TEXT
        )
    """)
    # Student-Class relation
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS student_classes (
            student_id INTEGER,
            class_id INTEGER,
            PRIMARY KEY (student_id, class_id)
        )
    """)
    # Settings table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    # Alerts table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER,
            type TEXT,
            message TEXT,
            created_at TEXT,
            seen INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()

init_db()

# ---------- LOGIN ----------
@app.route("/", methods=["GET","POST"])
def login():
    error = None
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        
        if not email or not password:
            error = "Email and password required"
        else:
            hashed = hash_password(password)
            conn = sqlite3.connect("attendance.db", timeout=10)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id,name FROM users WHERE email=? AND password=?",
                (email, hashed)
            )
            user = cursor.fetchone()
            conn.close()

            if user:
                session["user_id"] = user[0]
                session["user_name"] = user[1]
                # Remember me - 30 day session
                if request.form.get("remember"):
                    session.permanent = True
                    app.config["PERMANENT_SESSION_LIFETIME"] = 2592000  # 30 days
                return redirect("/dashboard")
            else:
                error = "Invalid email or password"

    return render_template("login.html", error=error)


# ---------- REGISTER ----------
@app.route("/register", methods=["GET","POST"])
def register():
    error = None
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        
        # Input validation
        if not name or len(name) < 2:
            error = "Name must be at least 2 characters"
        elif not email or "@" not in email:
            error = "Please enter a valid email address"
        elif not password or len(password) < 4:
            error = "Password must be at least 4 characters"
        else:
            try:
                hashed = hash_password(password)
                conn = sqlite3.connect("attendance.db", timeout=10)
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO users (name,email,password) VALUES (?,?,?)",
                    (name, email, hashed)
                )
                conn.commit()
                conn.close()
                return redirect("/")
            except sqlite3.IntegrityError:
                error = "Email already registered. Please use a different email."
            except Exception as e:
                error = f"Registration failed: {str(e)}"
    return render_template("register.html", error=error)


# ---------- DASHBOARD ----------
@app.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        return redirect("/")
    conn = sqlite3.connect("attendance.db", timeout=10)
    cursor = conn.cursor()
    
    # Total students
    cursor.execute("SELECT COUNT(*) FROM students")
    total = cursor.fetchone()[0]
    
    # Today's stats
    today = datetime.now().strftime("%Y-%m-%d")
    cursor.execute("SELECT COUNT(*) FROM attendance WHERE date=?", (today,))
    present = cursor.fetchone()[0]
    
    # Total attendance records all time
    cursor.execute("SELECT COUNT(*) FROM attendance")
    total_attendance = cursor.fetchone()[0]
    
    conn.close()
    absent = max(0, total - present)
    
    return render_template("dashboard.html", name=session["user_name"], total=total, 
                        present=present, absent=absent, total_attendance=total_attendance,
                        current_date=datetime.now().strftime("%Y-%m-%d"),
                        current_time=datetime.now().strftime("%H:%M:%S"))


# ---------- STUDENTS ----------
@app.route("/students", methods=["GET","POST"])
def students():
    if "user_id" not in session:
        return redirect("/")

    conn = sqlite3.connect("attendance.db", timeout=10)
    cursor = conn.cursor()
    error = None
    success = None

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        
        if not name or not email:
            error = "Name and email required"
        elif "@" not in email:
            error = "Invalid email format"
        else:
            # Check if email exists
            cursor.execute("SELECT id FROM students WHERE email=?", (email,))
            if cursor.fetchone():
                error = "Email already registered"
            else:
                # Generate and send OTP
                otp = generate_otp()
                expires = (datetime.now() + timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
                
                # Store OTP
                cursor.execute(
                    "INSERT INTO otp_verify (email, otp, expires_at) VALUES (?,?,?)",
                    (email, otp, expires)
                )
                conn.commit()
                
                # Send email
                if send_otp_email(email, otp):
                    session["pending_student"] = {"name": name, "email": email}
                    conn.close()
                    return redirect("/verify-otp")
                else:
                    error = "Failed to send OTP. Check email config."

    cursor.execute("SELECT id,name,email FROM students")
    students_list = cursor.fetchall()
    conn.close()

    return render_template("students.html", students=students_list, error=error, success=success)


# ---------- VERIFY OTP ----------
@app.route("/verify-otp", methods=["GET", "POST"])
def verify_otp():
    if "user_id" not in session:
        return redirect("/")
    
    pending = session.get("pending_student")
    if not pending:
        return redirect("/students")
    
    error = None
    
    if request.method == "POST":
        otp = request.form.get("otp", "").strip()
        
        conn = sqlite3.connect("attendance.db", timeout=10)
        cursor = conn.cursor()
        
        # Verify OTP
        cursor.execute(
            "SELECT id FROM otp_verify WHERE email=? AND otp=? AND used=0 AND expires_at > ?",
            (pending["email"], otp, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        )
        result = cursor.fetchone()
        
        if result:
            # Mark OTP as used
            cursor.execute("UPDATE otp_verify SET used=1 WHERE id=?", (result[0],))
            
            # Add student
            cursor.execute(
                "INSERT INTO students (name, email) VALUES (?,?)",
                (pending["name"], pending["email"])
            )
            conn.commit()
            conn.close()
            
            session.pop("pending_student", None)
            return redirect("/students")
        else:
            error = "Invalid or expired OTP"
            conn.close()
    
    return render_template("verify_otp.html", email=pending["email"], error=error)


# ---------- RESEND OTP ----------
@app.route("/resend-otp")
def resend_otp():
    if "user_id" not in session:
        return redirect("/")
    
    pending = session.get("pending_student")
    if not pending:
        return redirect("/students")
    
    conn = sqlite3.connect("attendance.db", timeout=10)
    cursor = conn.cursor()
    
    # Generate new OTP
    otp = generate_otp()
    expires = (datetime.now() + timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
    
    cursor.execute(
        "INSERT INTO otp_verify (email, otp, expires_at) VALUES (?,?,?)",
        (pending["email"], otp, expires)
    )
    conn.commit()
    
    send_otp_email(pending["email"], otp)
    conn.close()
    
    return redirect("/verify-otp")


# ---------- REGISTER FACE ----------
@app.route("/register-face/<int:sid>")
def register_face(sid):
    print(f"=== Starting face registration for student {sid} ===")
    try:
        # First check camera
        print("Testing camera access...")
        test_cam = cv2.VideoCapture(0)
        if not test_cam.isOpened():
            print("ERROR: Cannot open camera")
            test_cam.release()
        else:
            # Try to read a frame
            ret, frame = test_cam.read()
            print(f"Camera test - opened: {test_cam.isOpened()}, ret: {ret}, frame shape: {frame.shape if ret else None}")
            test_cam.release()
        
        # Now capture images
        enc = capture_face_images(sid, num_images=10)
        if enc:
            conn = sqlite3.connect("attendance.db", timeout=10)
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE students SET face_encoding=? WHERE id=?",
                (enc, sid)
            )
            conn.commit()
            conn.close()
            print("Face images captured and stored!")
        else:
            print("No face images captured - check camera")
    except ImportError as e:
        print(f"ERROR: Missing library - {e}")
    except Exception as e:
        print(f"ERROR in face registration: {e}")
        import traceback
        traceback.print_exc()
    print("=== Finished face registration ===")
    return redirect("/students")


# ---------- ATTENDANCE ----------
@app.route("/attendance", methods=["GET","POST"])
def attendance():
    if "user_id" not in session:
        return redirect("/")

    conn = sqlite3.connect("attendance.db", timeout=10)
    cursor = conn.cursor()
    msg = None

    if request.method == "POST":
        # Check if auto-attendance
        if "auto_attend" in request.form:
            # Auto-attendance mode - scan all students
            cursor.execute("SELECT id, name, face_encoding FROM students WHERE face_encoding IS NOT NULL")
            all_students = cursor.fetchall()
            conn.close()  # Close DB before camera operations
            
            if all_students:
                student_id, student_name, unknown_detected = verify_face_auto(all_students)
                
                # Reconnect to DB for marking attendance
                if student_id:
                    conn = sqlite3.connect("attendance.db", timeout=10)
                    cursor = conn.cursor()
                    # Check if already marked today
                    today = datetime.now().strftime("%Y-%m-%d")
                    cursor.execute(
                        "SELECT id FROM attendance WHERE student_id=? AND date=?",
                        (student_id, today)
                    )
                    existing = cursor.fetchone()
                    
                    if not existing:
                        cursor.execute(
                            "INSERT INTO attendance (student_id, date, time) VALUES (?,?,?)",
                            (student_id, today, datetime.now().strftime("%H:%M:%S"))
                        )
                        conn.commit()
                        msg = f"Attendance marked for {student_name}!"
                    else:
                        conn.close()
                        msg = f"{student_name} is already marked present today!"
                        return render_template("attendance.html", students=[], message=msg)
                    conn.close()
                elif unknown_detected:
                    msg = "Unknown person detected. Face not registered."
                else:
                    msg = "No face detected. Please try again."
            else:
                msg = "No students with registered faces found."
        else:
            # Individual attendance mode (select from dropdown)
            sid = request.form["student_id"]
            cursor.execute("SELECT face_encoding FROM students WHERE id=?", (sid,))
            data = cursor.fetchone()
            conn.close()  # Close DB before camera operations

            if data and data[0]:
                try:
                    verified, _ = verify_face(data[0])
                    
                    if verified:
                        # Reconnect to DB for marking attendance
                        conn = sqlite3.connect("attendance.db", timeout=10)
                        cursor = conn.cursor()
                        cursor.execute(
                            "INSERT INTO attendance (student_id, date, time) VALUES (?,?,?)",
                            (sid, datetime.now().strftime("%Y-%m-%d"), datetime.now().strftime("%H:%M:%S"))
                        )
                        conn.commit()
                        conn.close()
                        msg = "Attendance marked successfully!"
                    else:
                        msg = "Face not recognized. Please try again."
                except Exception as e:
                    msg = f"Error: {str(e)}"
            else:
                msg = "Face not registered. Please register face first."

    # Fresh connection for SELECT to avoid cursor issues
    conn = sqlite3.connect("attendance.db", timeout=10)
    cursor = conn.cursor()
    cursor.execute("SELECT id,name FROM students")
    students = cursor.fetchall()
    conn.close()

    return render_template("attendance.html", students=students, message=msg)


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


# ---------- DELETE STUDENT ----------
@app.route("/delete-student/<int:sid>")
def delete_student(sid):
    if "user_id" not in session:
        return redirect("/")
    
    conn = sqlite3.connect("attendance.db", timeout=10)
    cursor = conn.cursor()
    # Delete attendance records first
    cursor.execute("DELETE FROM attendance WHERE student_id=?", (sid,))
    # Delete face encoding
    cursor.execute("DELETE FROM students WHERE id=?", (sid,))
    conn.commit()
    conn.close()
    return redirect("/students")


# ---------- EDIT STUDENT ----------
@app.route("/edit-student/<int:sid>", methods=["GET", "POST"])
def edit_student(sid):
    if "user_id" not in session:
        return redirect("/")
    
    conn = sqlite3.connect("attendance.db", timeout=10)
    cursor = conn.cursor()
    
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        
        if name and email:
            cursor.execute(
                "UPDATE students SET name=?, email=? WHERE id=?",
                (name, email, sid)
            )
            conn.commit()
            conn.close()
            return redirect("/students")
        else:
            conn.close()
            return render_template("edit_student.html", error="Name and email required", student={"id": sid, "name": request.form.get("name", ""), "email": request.form.get("email", "")})
    
    # GET: show edit form
    cursor.execute("SELECT id, name, email FROM students WHERE id=?", (sid,))
    student = cursor.fetchone()
    conn.close()
    
    if student:
        return render_template("edit_student.html", student=student)
    else:
        return redirect("/students")


# ---------- EXPORT ATTENDANCE ----------
@app.route("/export")
def export_attendance():
    if "user_id" not in session:
        return redirect("/")
    
    import csv
    from io import StringIO
    from flask import Response
    
    conn = sqlite3.connect("attendance.db", timeout=10)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT students.name, attendance.date, attendance.time
        FROM attendance
        JOIN students ON students.id = attendance.student_id
        ORDER BY attendance.date DESC, attendance.time DESC
    """)
    
    records = cursor.fetchall()
    conn.close()
    
    # Create CSV
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["Student Name", "Date", "Time"])
    for row in records:
        writer.writerow(row)
    
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-disposition": "attachment; filename=attendance.csv"}
    )


# ---------- EXPORT REPORT ----------
@app.route("/export-report")
def export_report():
    if "user_id" not in session:
        return redirect("/")
    
    import csv
    from io import StringIO
    from flask import Response
    
    format_type = request.args.get("format", "csv")
    
    conn = sqlite3.connect("attendance.db", timeout=10)
    cursor = conn.cursor()
    
    # Get all students with attendance
    cursor.execute("""
        SELECT s.id, s.name, s.email,
               (SELECT COUNT(*) FROM attendance WHERE student_id = s.id) as attended
        FROM students s
        ORDER BY s.name
    """)
    students = cursor.fetchall()
    
    # Get total days
    cursor.execute("SELECT COUNT(DISTINCT date) FROM attendance")
    total_days = cursor.fetchone()[0] or 1
    conn.close()
    
    # Create output
    output = StringIO()
    writer = csv.writer(output)
    
    if format_type == "excel":
        writer.writerow(["ID", "Name", "Email", "Days Attended", "Attendance %", "Status"])
        for s in students:
            pct = round((s[3] / total_days) * 100, 1) if total_days > 0 else 0
            status = "Excellent" if pct >= 90 else "Good" if pct >= 70 else "Fair" if pct >= 50 else "Low"
            writer.writerow([s[0], s[1], s[2], s[3], f"{pct}%", status])
        filename = "student_report.csv"
    else:
        writer.writerow(["Student Name", "Email", "Days Attended", "Attendance %"])
        for s in students:
            pct = round((s[3] / total_days) * 100, 1) if total_days > 0 else 0
            writer.writerow([s[1], s[2], s[3], f"{pct}%"])
        filename = "report.csv"
    
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-disposition": f"attachment; filename={filename}"}
    )


# ---------- HISTORY WITH FILTERS ----------
@app.route("/history", methods=["GET", "POST"])
def history():
    if "user_id" not in session:
        return redirect("/")
    
    # Get date filters
    start_date = request.args.get("start_date", "")
    end_date = request.args.get("end_date", "")
    student_filter = request.args.get("student_id", "")
    
    conn = sqlite3.connect("attendance.db", timeout=10)
    cursor = conn.cursor()
    
    query = """
        SELECT students.name, attendance.date, attendance.time, students.id
        FROM attendance
        JOIN students ON students.id = attendance.student_id
        WHERE 1=1
    """
    params = []
    
    if start_date:
        query += " AND attendance.date >= ?"
        params.append(start_date)
    if end_date:
        query += " AND attendance.date <= ?"
        params.append(end_date)
    if student_filter:
        query += " AND students.id = ?"
        params.append(student_filter)
    
    query += " ORDER BY attendance.id DESC"
    
    cursor.execute(query, params)
    records = cursor.fetchall()
    
    # Get all students for dropdown
    cursor.execute("SELECT id, name FROM students ORDER BY name")
    students = cursor.fetchall()
    conn.close()
    
    return render_template("history.html", records=records, students=students, 
                         start_date=start_date, end_date=end_date, student_filter=student_filter)


# ---------- STUDENT ATTENDANCE REPORT ----------
@app.route("/reports")
def reports():
    if "user_id" not in session:
        return redirect("/")
    
    conn = sqlite3.connect("attendance.db", timeout=10)
    cursor = conn.cursor()
    
    # Get all students with their attendance stats
    cursor.execute("SELECT id, name, email FROM students ORDER BY name")
    all_students = cursor.fetchall()
    
    # Get total days attendance was taken
    cursor.execute("SELECT COUNT(DISTINCT date) FROM attendance")
    total_days = cursor.fetchone()[0] or 1
    
    student_stats = []
    for s in all_students:
        sid, name, email = s
        # Count attended days
        cursor.execute("SELECT COUNT(*) FROM attendance WHERE student_id=?", (sid,))
        attended = cursor.fetchone()[0]
        percentage = round((attended / total_days) * 100, 1) if total_days > 0 else 0
        student_stats.append({
            "id": sid,
            "name": name,
            "email": email,
            "attended": attended,
            "percentage": percentage
        })
    
    conn.close()
    
    return render_template("reports.html", student_stats=student_stats, total_days=total_days)


# ---------- SEARCH STUDENTS ----------
@app.route("/search")
def search():
    if "user_id" not in session:
        return redirect("/")
    
    query = request.args.get("q", "").strip()
    
    conn = sqlite3.connect("attendance.db", timeout=10)
    cursor = conn.cursor()
    
    if query:
        cursor.execute(
            "SELECT id, name, email FROM students WHERE name LIKE ? OR email LIKE ? ORDER BY name",
            (f"%{query}%", f"%{query}%")
        )
    else:
        cursor.execute("SELECT id, name, email FROM students ORDER BY name")
    
    students = cursor.fetchall()
    conn.close()
    
    return render_template("search.html", students=students, query=query)


# ---------- WEEKLY SUMMARY ----------
@app.route("/summary")
def summary():
    if "user_id" not in session:
        return redirect("/")
    
    conn = sqlite3.connect("attendance.db", timeout=10)
    cursor = conn.cursor()
    
    # Last 7 days attendance
    cursor.execute("""
        SELECT date, COUNT(*) as count 
        FROM attendance 
        WHERE date >= date('now', '-7 days')
        GROUP BY date 
        ORDER BY date DESC
    """)
    weekly = cursor.fetchall()
    
    # Total students
    cursor.execute("SELECT COUNT(*) FROM students")
    total_students = cursor.fetchone()[0]
    
    # Average attendance
    cursor.execute("SELECT AVG(daily_count) FROM (SELECT COUNT(*) as daily_count FROM attendance GROUP BY date)")
    avg_attendance = cursor.fetchone()[0] or 0
    
    conn.close()
    
    return render_template("summary.html", weekly=weekly, total_students=total_students, 
                         avg_attendance=round(avg_attendance, 1))


# ---------- ADMIN SETTINGS ----------
@app.route("/settings", methods=["GET", "POST"])
def settings():
    if "user_id" not in session:
        return redirect("/")
    
    error = None
    success = None
    
    conn = sqlite3.connect("attendance.db", timeout=10)
    cursor = conn.cursor()
    
    if request.method == "POST":
        action = request.form.get("action")
        
        if action == "change_password":
            current = request.form.get("current_password", "")
            new_pass = request.form.get("new_password", "")
            confirm = request.form.get("confirm_password", "")
            
            # Verify current password
            cursor.execute("SELECT password FROM users WHERE id=?", (session["user_id"],))
            stored_hash = cursor.fetchone()[0]
            
            if hash_password(current) != stored_hash:
                error = "Current password is incorrect"
            elif len(new_pass) < 4:
                error = "New password must be at least 4 characters"
            elif new_pass != confirm:
                error = "New passwords do not match"
            else:
                cursor.execute(
                    "UPDATE users SET password=? WHERE id=?",
                    (hash_password(new_pass), session["user_id"])
                )
                conn.commit()
                success = "Password changed successfully!"
        
        elif action == "update_profile":
            name = request.form.get("name", "").strip()
            if name and len(name) >= 2:
                cursor.execute(
                    "UPDATE users SET name=? WHERE id=?",
                    (name, session["user_id"])
                )
                conn.commit()
                session["user_name"] = name
                success = "Profile updated successfully!"
            else:
                error = "Name must be at least 2 characters"
    
    # Get user info
    cursor.execute("SELECT name, email FROM users WHERE id=?", (session["user_id"],))
    user = cursor.fetchone()
    conn.close()
    
    return render_template("settings.html", user=user, error=error, success=success)


# ---------- RESET TODAY'S ATTENDANCE ----------
@app.route("/reset-today", methods=["GET", "POST"])
def reset_today():
    if "user_id" not in session:
        return redirect("/")
    
    error = None
    
    if request.method == "POST":
        password = request.form.get("password", "")
        
        # Verify password
        conn = sqlite3.connect("attendance.db", timeout=10)
        cursor = conn.cursor()
        hashed = hash_password(password)
        cursor.execute("SELECT id FROM users WHERE id=? AND password=?", 
                     (session["user_id"], hashed))
        if not cursor.fetchone():
            error = "Incorrect password"
            conn.close()
            return render_template("confirm_reset.html", error=error)
        
        # Reset attendance
        today = datetime.now().strftime("%Y-%m-%d")
        cursor.execute("DELETE FROM attendance WHERE date=?", (today,))
        conn.commit()
        conn.close()
        return redirect("/history")
    
    return render_template("confirm_reset.html", error=error)


# ---------- BULK DELETE STUDENTS ----------
@app.route("/bulk-delete", methods=["POST"])
def bulk_delete():
    if "user_id" not in session:
        return redirect("/")
    
    student_ids = request.form.getlist("student_ids")
    
    if student_ids:
        conn = sqlite3.connect("attendance.db", timeout=10)
        cursor = conn.cursor()
        for sid in student_ids:
            cursor.execute("DELETE FROM attendance WHERE student_id=?", (sid,))
            cursor.execute("DELETE FROM students WHERE id=?", (sid,))
        conn.commit()
        conn.close()
    
    return redirect("/students")


# ---------- SORTED STUDENTS BY ATTENDANCE ----------
@app.route("/students-sorted")
def students_sorted():
    if "user_id" not in session:
        return redirect("/")
    
    sort = request.args.get("sort", "attendance")  # attendance or name
    
    conn = sqlite3.connect("attendance.db", timeout=10)
    cursor = conn.cursor()
    
    # Get total days
    cursor.execute("SELECT COUNT(DISTINCT date) FROM attendance")
    total_days = cursor.fetchone()[0] or 1
    
    if sort == "name":
        cursor.execute("""
            SELECT s.id, s.name, s.email, 
                   COALESCE((SELECT COUNT(*) FROM attendance WHERE student_id = s.id), 0) as attended
            FROM students s
            ORDER BY s.name
        """)
    else:
        # Sort by attendance percentage
        cursor.execute("""
            SELECT s.id, s.name, s.email, 
                   COALESCE((SELECT COUNT(*) FROM attendance WHERE student_id = s.id), 0) as attended,
                   (SELECT COUNT(DISTINCT date) FROM attendance) as total
            FROM students s
            ORDER BY attended DESC
        """)
    
    students = cursor.fetchall()
    conn.close()
    
    return render_template("students_sorted.html", students=students, total_days=total_days, sort=sort)


# ---------- ALERTS & LOW ATTENDANCE ----------
@app.route("/alerts")
def alerts():
    if "user_id" not in session:
        return redirect("/")
    
    conn = sqlite3.connect("attendance.db", timeout=10)
    cursor = conn.cursor()
    
    # Check for low attendance (less than 50% this week)
    today = datetime.now().strftime("%Y-%m-%d")
    cursor.execute("""
        SELECT s.id, s.name, 
               (SELECT COUNT(*) FROM attendance WHERE student_id = s.id AND date >= date('now', '-7 days')) as recent
        FROM students s
    """)
    
    cursor.execute("SELECT COUNT(DISTINCT date) FROM attendance WHERE date >= date('now', '-7 days')")
    days = cursor.fetchone()[0] or 1
    
    for s in cursor.fetchall():
        pct = (s[2] / days * 100) if days > 0 else 0
        if pct < 50:
            # Check if alert already exists
            cursor.execute(
                "SELECT id FROM alerts WHERE student_id=? AND type='low_attendance' AND seen=0",
                (s[0],)
            )
            if not cursor.fetchone():
                cursor.execute(
                    "INSERT INTO alerts (student_id, type, message, created_at) VALUES (?,?,?,?)",
                    (s[0], "low_attendance", f"Low attendance: {pct:.0f}% this week", today)
                )
    
    conn.commit()
    
    # Get unseen alerts
    cursor.execute("""
        SELECT a.id, a.type, a.message, a.created_at, s.name
        FROM alerts a
        JOIN students s ON s.id = a.student_id
        WHERE a.seen=0
        ORDER BY a.id DESC
    """)
    alerts_list = cursor.fetchall()
    conn.close()
    
    return render_template("alerts.html", alerts=alerts_list)


@app.route("/dismiss-alert/<int:aid>")
def dismiss_alert(aid):
    if "user_id" not in session:
        return redirect("/")
    
    conn = sqlite3.connect("attendance.db", timeout=10)
    cursor = conn.cursor()
    cursor.execute("UPDATE alerts SET seen=1 WHERE id=?", (aid,))
    conn.commit()
    conn.close()
    return redirect("/alerts")


# ---------- TRENDS CHART DATA ----------
@app.route("/trends")
def trends():
    if "user_id" not in session:
        return redirect("/")
    
    days = request.args.get("days", "30")
    
    conn = sqlite3.connect("attendance.db", timeout=10)
    cursor = conn.cursor()
    
    cursor.execute(f"""
        SELECT date, COUNT(*) as count 
        FROM attendance 
        WHERE date >= date('now', '-{days} days')
        GROUP BY date 
        ORDER BY date
    """)
    data = cursor.fetchall()
    
    cursor.execute("SELECT COUNT(*) FROM students")
    total_students = cursor.fetchone()[0]
    
    conn.close()
    
    return render_template("trends.html", data=data, total_students=total_students, days=days)


# ---------- DAILY SUMMARY ----------
@app.route("/daily-summary")
def daily_summary():
    if "user_id" not in session:
        return redirect("/")
    
    today = datetime.now().strftime("%Y-%m-%d")
    
    conn = sqlite3.connect("attendance.db", timeout=10)
    cursor = conn.cursor()
    
    # Total students
    cursor.execute("SELECT COUNT(*) FROM students")
    total = cursor.fetchone()[0]
    
    # Present today
    cursor.execute("SELECT COUNT(*) FROM attendance WHERE date=?", (today,))
    present = cursor.fetchone()[0]
    
    # Recent trend
    cursor.execute("""
        SELECT date, COUNT(*) 
        FROM attendance 
        WHERE date >= date('now', '-7 days')
        GROUP BY date
        ORDER BY date DESC
    """)
    week = cursor.fetchall()
    
    conn.close()
    
    absent = total - present
    pct = round((present / total * 100), 1) if total > 0 else 0
    
    return render_template("daily_summary.html", 
                     total=total, present=present, absent=absent, 
                     percentage=pct, week=week, date=today)


# ---------- CHECK LOW ATTENDANCE (API) ----------
@app.route("/check-alerts")
def check_alerts():
    if "user_id" not in session:
        return redirect("/")
    
    conn = sqlite3.connect("attendance.db", timeout=10)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM alerts WHERE seen=0")
    count = cursor.fetchone()[0]
    conn.close()
    
    return str(count)


# ---------- CUSTOMER SERVICES / QUERY ----------
@app.route("/services", methods=["GET", "POST"])
def services():
    if "user_id" not in session:
        return redirect("/")
    
    conn = sqlite3.connect("attendance.db", timeout=10)
    cursor = conn.cursor()
    
    # Create queries table if not exists
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS queries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            subject TEXT,
            message TEXT,
            status TEXT DEFAULT 'pending',
            created_at TEXT
        )
    """)
    
    if request.method == "POST":
        subject = request.form.get("subject", "").strip()
        message = request.form.get("message", "").strip()
        if subject and message:
            cursor.execute(
                "INSERT INTO queries (user_id, subject, message, created_at) VALUES (?,?,?,?)",
                (session["user_id"], subject, message, datetime.now().strftime("%Y-%m-%d %H:%M"))
            )
            conn.commit()
    
    # Get user's queries
    cursor.execute(
        "SELECT id, subject, message, status, created_at FROM queries WHERE user_id=? ORDER BY id DESC",
        (session["user_id"],)
    )
    queries = cursor.fetchall()
    conn.close()
    
    return render_template("services.html", queries=queries)


# ---------- VIEW QUERY ----------
@app.route("/query/<int:qid>")
def view_query(qid):
    if "user_id" not in session:
        return redirect("/")
    
    conn = sqlite3.connect("attendance.db", timeout=10)
    cursor = conn.cursor()
    cursor.execute("SELECT id, subject, message, status, created_at FROM queries WHERE id=?", (qid,))
    query = cursor.fetchone()
    conn.close()
    
    if query:
        return render_template("view_query.html", query=query)
    return redirect("/services")


# ---------- ABOUT PAGE ----------
@app.route("/about")
def about():
    return render_template("about.html")


if __name__ == "__main__":
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(debug=debug)