from fastapi import FastAPI, Form, File, UploadFile, Request, HTTPException, Query, Response, APIRouter
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.security import HTTPBearer
from pydantic import BaseModel, EmailStr
from datetime import datetime, timedelta
from pymongo import MongoClient
import hashlib
import base64
import os
import zipfile
import gridfs
import pandas as pd
from bson import ObjectId
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from io import BytesIO
import random
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import math
import re
from jinja2 import Environment, FileSystemLoader
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Image, Spacer
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import secrets
import jwt




# Initialize Jinja2 Environment safely
jinja_env = Environment(loader=FileSystemLoader("templates"))


# ----------------------------
# MongoDB Connection
# ----------------------------
# 🔹 For local MongoDB (default)
client = MongoClient("mongodb://localhost:27017")

# 🔹 Database and Collection
db = client["studentDB"]
academic_collection = db["academic"]
personal_collection = db["personal"]
other_collection = db["other_detail"]
login_collection = db["login"]
register_collection = db["register"] 
resume_parsed_collection = db["resume_parsed"]
collection = db["match_scores"]

db = client["tpo_db"]
fs = gridfs.GridFS(db)

personal_collection.create_index("prn", unique=True)


# Helper function to hash password
# ----------------------------
def hash_password(password: str):
    return hashlib.sha256(password.encode()).hexdigest()

# JWT Configuration
SECRET_KEY = "your-secret-key-here"  # Change this to a secure secret key
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def verify_token(token: str):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

# OTP Store (in production, use Redis or DB)
otp_store = {}  # {email: {"otp": str, "expires": datetime}}

# Email Configuration (replace with your Gmail credentials)
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_EMAIL = "your-email@gmail.com"  # Replace with your Gmail
SMTP_PASSWORD = "your-app-password"  # Replace with Gmail App Password

def send_otp_email(email: str, otp: str):
    # For testing purposes, skip actual email sending
    print(f"OTP for {email}: {otp}")  # Print OTP for testing
    return True

security = HTTPBearer()

# ----------------------------
# FastAPI App Setup
# ----------------------------
app = FastAPI()
templates = Jinja2Templates(directory="templates")
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")
# ✅ Serve profile pictures or static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# 🔹 Allow frontend requests (CORS)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # You can replace "*" with specific frontend URL (e.g., http://127.0.0.1:5500)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# Folder for saving uploaded images
UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

#basemodel for register
class RegisterUser(BaseModel):
    email: EmailStr
    password: str

# Pydantic Model for Login
class LoginUser(BaseModel):
    email: EmailStr
    password: str

# ➕ Model for Personal Details
class PersonalDetails(BaseModel):
    prn: str 
    name: str
    email: EmailStr
    phone: str
    dob: str
    address: str
    profile_summary:str
   

# ➕ Model for Other Details
class OtherDetails(BaseModel):
    skills: str
    hobbies: str
    certifications: str
    achievements: str

# Data Model for Validation
class AcademicDetails(BaseModel):
    xName: str
    xPercentage: str
    xiiName: str
    xiiStream: str
    xiiPercentage: str
    degree: str
    department: str
    college: str
    year: str
    cgpa: str
    project: str
    internship: str

# ----------------------------

# ----------------------------
# Get Students by Department
# ----------------------------
@app.get("/students/{dept}")
def get_students_by_department(dept: str):
    """
    Fetch all students from a given department (case-insensitive).
    """
    students = list(academic_collection.find({"department": {"$regex": f"^{dept}$", "$options": "i"}}))

    # Convert ObjectIds
    for s in students:
        s["_id"] = str(s["_id"])

    if not students:
        return {"department": dept, "students": []}

    return {"department": dept, "students": students}


# API Endpoint
# ----------------------------
@app.post("/api/academic")
async def save_academic_details(
    student_id: str = Form(...),
    xName: str = Form(...),
    xPercentage: str = Form(...),
    xiiName: str = Form(...),
    xiiStream: str = Form(...),
    xiiPercentage: str = Form(...),
    degree: str = Form(...),
    department: str = Form(...),
    college: str = Form(...),
    year: str = Form(...),
    cgpa: str = Form(...),
    project: str = Form(...),
    internship: str = Form(...)
):
    # ✅ Base academic data
    data = {
        "xName": xName,
        "xPercentage": xPercentage,
        "xiiName": xiiName,
        "xiiStream": xiiStream,
        "xiiPercentage": xiiPercentage,
        "degree": degree,
        "department": department,
        "college": college,
        "year": year,
        "cgpa": cgpa,
        "updated_at": datetime.utcnow()
    }

    # ✅ Update basic details (will not remove old projects/internships)
    academic_collection.update_one(
        {"student_id": student_id},
        {"$set": data, "$setOnInsert": {"student_id": student_id}},
        upsert=True
    )

    # ✅ Append project/internship without removing old ones
    academic_collection.update_one(
        {"student_id": student_id},
        {
            "$addToSet": {
                "projects": project,
                "internships": internship
            }
        },
        upsert=True
    )

    # ✅ Also maintain backward-compatible single fields for easy frontend display
    existing_data = academic_collection.find_one({"student_id": student_id})
    projects_list = existing_data.get("projects", [])
    internships_list = existing_data.get("internships", [])

    academic_collection.update_one(
        {"student_id": student_id},
        {
            "$set": {
                "project": ", ".join([p for p in projects_list if p]),  # old format
                "internship": ", ".join([i for i in internships_list if i])
            }
        }
    )

    return {"message": "Academic details added successfully without removing old data!"}

# ----------------------------


# ➕ Endpoint to save personal details
@app.post("/api/personal")
async def save_personal_details(
    student_id: str = Form(...),
    prn: str = Form(...),
    name: str = Form(...),
    email: str = Form(...),
    phone: str = Form(...),
    dob: str = Form(...),
    address: str = Form(...),
    profile_summary: str = Form(...),
    profile_photo: UploadFile = File(None)
):
    try:
        profile_data = None

        if profile_photo:
            file_location = os.path.join("uploads", profile_photo.filename)

            with open(file_location, "wb") as f:
                f.write(await profile_photo.read())

            # FIX: convert "\" → "/"
            profile_data = file_location.replace("\\", "/")

        update_data = {
            "prn": prn,
            "name": name,
            "email": email,
            "phone": phone,
            "dob": dob,
            "address": address,
        }

        existing = personal_collection.find_one({"student_id": student_id})
        if existing and existing.get("profile_summary"):
            update_data["profile_summary"] = existing["profile_summary"] + " " + profile_summary
        else:
            update_data["profile_summary"] = profile_summary

        if profile_data:
            update_data["profile_photo"] = profile_data

        personal_collection.update_one(
            {"student_id": student_id},
            {"$set": update_data},
            upsert=True
        )

        return {"success": True, "message": "Personal details saved/updated successfully!"}

    except Exception as e:
        return {"success": False, "message": str(e)}

# ➕ Endpoint to save 'Other Details'
@app.post("/api/other")
async def save_other_details(
    student_id: str = Form(...),
    skills: str = Form(""),
    hobbies: str = Form(""),
    certifications: str = Form(""),
    achievements: str = Form("")
):
    # ✅ Always normalize incoming strings
    skills = skills.strip()
    hobbies = hobbies.strip()
    certifications = certifications.strip()
    achievements = achievements.strip()

    # ✅ Find existing document for this student_id
    existing_data = other_collection.find_one({"student_id": student_id})

    if existing_data:
        # Helper to merge old and new comma-separated data safely
        def merge_field(old_value, new_value):
            old_items = [x.strip() for x in old_value.split(",") if x.strip()] if old_value else []
            new_items = [x.strip() for x in new_value.split(",") if x.strip()] if new_value else []
            merged = list(dict.fromkeys(old_items + new_items))  # preserve order, avoid duplicates
            return ", ".join(merged)

        updated_data = {
            "skills": merge_field(existing_data.get("skills", ""), skills),
            "hobbies": merge_field(existing_data.get("hobbies", ""), hobbies),
            "certifications": merge_field(existing_data.get("certifications", ""), certifications),
            "achievements": merge_field(existing_data.get("achievements", ""), achievements),
            "updated_at": datetime.utcnow()
        }

        # ✅ Update in place — no new document created
        other_collection.update_one(
            {"student_id": student_id},
            {"$set": updated_data}
        )
        message = "Existing record updated successfully!"
    else:
        # ✅ Insert once for first-time entry
        data = {
            "student_id": student_id,
            "skills": skills,
            "hobbies": hobbies,
            "certifications": certifications,
            "achievements": achievements,
            "created_at": datetime.utcnow()
        }
        other_collection.insert_one(data)
        message = "New record created successfully!"

    return {"message": message}


 # End point of student registartion
@app.post("/register")
async def register_user(user: RegisterUser):
    hashed_pw = hash_password(user.password)

    # Check if email already exists
    existing_user = register_collection.find_one({"email": user.email})
    if existing_user:
        return JSONResponse(
            status_code=400,
            content={"success": False, "message": "Email already registered"}
        )
     # 2️⃣ Generate a unique student_id
    last_user = register_collection.find_one(sort=[("_id", -1)])
    if last_user and "student_id" in last_user:
        # Extract number from last student_id (e.g., S1001 → 1001)
        last_num = int(last_user["student_id"][1:])
        student_id = f"S{last_num + 1}"
    else:
        student_id = "S1001"

    # Insert user into MongoDB
    register_collection.insert_one({
        "student_id": student_id,
        "email": user.email,
        "password": hashed_pw,
        "created_at": datetime.utcnow()
    })

    # 4️⃣ Send student_id in response
    return JSONResponse(
        status_code=201,
        content={
            "success": True,
            "message": "Registration successful",
            "student_id": student_id
        }
    )

# ----------------------------
# Test endpoint
# ----------------------------
@app.get("/")
async def home():
    return {"message": "FastAPI server is running 🚀"}

# Login Endpoint
# ----------------------------
@app.post("/api/login")
async def login_user(user: LoginUser):
    email = user.email
    password = user.password

    # Hash entered password
    hashed_pw = hash_password(password)

    # Find user in registration collection
    existing_user = register_collection.find_one({"email": email})

    # Log attempt
    login_log = {
        "email": email,
        "login_time": datetime.utcnow(),
        "status": "Failed"  # Default to failed
    }

    if not existing_user:
        login_collection.insert_one(login_log)
        raise HTTPException(status_code=401, detail="User not found")

    # Check password match
    if existing_user["password"] != hashed_pw:
        login_collection.insert_one(login_log)
        raise HTTPException(status_code=401, detail="Invalid password")

    # If login successful
    login_log["status"] = "Success"
    login_collection.insert_one(login_log)

    # Check if this is the TPO email
    if email == "tpokbp1213@gmail.com":
        return JSONResponse(
            content={
                "success": True,
                "message": "TPO Login successful!",
                "role": "tpo"
            },
            status_code=200
        )

    return JSONResponse(
        content={
            "success": True,
            "message": "Login successful!",
            "student_id": existing_user["student_id"]
        },
        status_code=200
    )

# Forgot Password Endpoint
@app.post("/forgot-password")
async def forgot_password(request: Request):
    data = await request.json()
    email = data.get("email")

    if not email:
        raise HTTPException(status_code=400, detail="Email is required")

    # Check if user exists
    user = register_collection.find_one({"email": email})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Generate 6-digit OTP (fixed for testing)
    otp = "123456"
    expires = datetime.utcnow() + timedelta(minutes=5)

    # Store OTP
    otp_store[email] = {"otp": otp, "expires": expires}

    # Send OTP email
    if send_otp_email(email, otp):
        return {"message": "OTP sent to your email"}
    else:
        raise HTTPException(status_code=500, detail="Failed to send email")

# Verify OTP Endpoint
@app.post("/verify-otp")
async def verify_otp(request: Request):
    data = await request.json()
    email = data.get("email")
    otp = data.get("otp")

    if not email or not otp:
        raise HTTPException(status_code=400, detail="Email and OTP are required")

    if email not in otp_store:
        raise HTTPException(status_code=400, detail="OTP not requested")

    stored = otp_store[email]
    if datetime.utcnow() > stored["expires"]:
        del otp_store[email]
        raise HTTPException(status_code=400, detail="OTP expired")

    if stored["otp"] != otp:
        raise HTTPException(status_code=400, detail="Invalid OTP")

    # OTP verified, generate reset token
    reset_token = secrets.token_urlsafe(32)
    payload = {"email": email, "exp": datetime.utcnow() + timedelta(minutes=15)}
    reset_token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

    # Clean up OTP
    del otp_store[email]

    return {"message": "OTP verified", "reset_token": reset_token}

# Reset Password Endpoint
@app.post("/reset-password")
async def reset_password(request: Request):
    data = await request.json()
    reset_token = data.get("reset_token")
    new_password = data.get("newPassword")

    if not reset_token or not new_password:
        raise HTTPException(status_code=400, detail="Reset token and new password are required")

    try:
        payload = jwt.decode(reset_token, SECRET_KEY, algorithms=[ALGORITHM])
        email = payload.get("email")
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Reset token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid reset token")

    # Update password
    hashed_pw = hash_password(new_password)
    register_collection.update_one({"email": email}, {"$set": {"password": hashed_pw}})

    return {"message": "Password reset successful"}
#resume
@app.get("/get_resume_data/{student_id}")
def get_resume_data(student_id: str):
    """
    Fetch combined resume data for a student using student_id
    """

    # Fetch from all collections
    register_data = register_collection.find_one({"student_id": student_id})
    personal_data = personal_collection.find_one({"student_id": student_id})
    academic_data = academic_collection.find_one({"student_id": student_id})
    other_data = other_collection.find_one({"student_id": student_id})

    if not (register_data or personal_data):
        raise HTTPException(status_code=404, detail="Student not found")

    # --- Helper to convert comma-separated string to list ---
    def split_list(value):
        if not value:
            return []
        if isinstance(value, list):
            return value
        return [item.strip() for item in value.split(",") if item.strip()]

    # --- Combine all data into the expected frontend format ---
    # Handle profile photo as base64 for PDF embedding
    profile_photo_base64 = ""
    if personal_data and personal_data.get("profile_photo"):
        photo_path = personal_data["profile_photo"].replace("\\", "/")
        if os.path.exists(photo_path):
            with open(photo_path, "rb") as f:
                photo_data = f.read()
                profile_photo_base64 = base64.b64encode(photo_data).decode('utf-8')

    result = {
        "student_id": student_id,

        # Personal Info
        "name": personal_data.get("name", "") if personal_data else "",
        "email": personal_data.get("email", "") if personal_data else "",
        "phone": personal_data.get("phone", "") if personal_data else "",
        "address": personal_data.get("address", "") if personal_data else "",
        "profile_photo": personal_data.get("profile_photo", "") if personal_data else "",
        "profile_photo_base64": profile_photo_base64,
        "profile_summary": personal_data.get("profile_summary", "") if personal_data else "",

        # Skills, Strengths (from hobbies), Achievements
        "skills": split_list(other_data.get("skills", "")) if other_data else [],
        "strengths": split_list(other_data.get("hobbies", "")) if other_data else [],
        "achievements": split_list(other_data.get("achievements", "")) if other_data else [],

        # Education (grouped in one list)
        "education": [
            {
                "degree": academic_data.get("degree", ""),
                "institute": academic_data.get("college", ""),
                "year": academic_data.get("year", ""),
                "score": academic_data.get("cgpa", "")
            },
            {
                "degree": "12th - " + academic_data.get("xiiStream", ""),
                "institute": academic_data.get("xiiName", ""),
                "year": "",
                "score": academic_data.get("xiiPercentage", "")
            },
            {
                "degree": "10th",
                "institute": academic_data.get("xName", ""),
                "year": "",
                "score": academic_data.get("xPercentage", "")
            },
        ] if academic_data else [],

        # Project Summary + Projects
        
        "projects": [
            {"title": academic_data.get("project", ""), "description": ""}
        ] if academic_data else [],

        # Internship
        "internships": [
            {"company": academic_data.get("internship", ""), "role": "", "duration": ""}
        ] if academic_data else [],
    }

    return result

#download resume as pdf


@app.get("/api/download_resume/{student_id}")
def download_resume(student_id: str):

    # Fetch data
    personal = personal_collection.find_one({"student_id": student_id}) or {}
    academic = academic_collection.find_one({"student_id": student_id}) or {}
    other = other_collection.find_one({"student_id": student_id}) or {}

    # Create folder for PDFs
    os.makedirs("generated", exist_ok=True)
    pdf_path = f"generated/{student_id}_resume.pdf"

    # PDF template setup
    doc = SimpleDocTemplate(pdf_path, pagesize=letter)
    styles = getSampleStyleSheet()
    story = []

    # ---------- PROFILE PHOTO ----------
    profile_photo_path = personal.get("profile_photo")

    if profile_photo_path:
        # Convert stored "uploads\photo.jpg" → "uploads/photo.jpg"
        profile_photo_path = profile_photo_path.replace("\\", "/")

        if os.path.exists(profile_photo_path):
            img = Image(profile_photo_path, width=100, height=100)
            story.append(img)
            story.append(Spacer(1, 12))

    # ---------- BASIC DETAILS ----------
    story.append(Paragraph(f"<b>Name:</b> {personal.get('name','')}", styles["Normal"]))
    story.append(Paragraph(f"<b>Email:</b> {personal.get('email','')}", styles["Normal"]))
    story.append(Paragraph(f"<b>Phone:</b> {personal.get('phone','')}", styles["Normal"]))
    story.append(Spacer(1, 12))

    # ---------- SKILLS ----------
    skills = other.get("skills", "")
    story.append(Paragraph("<b>Skills:</b> " + skills, styles["Normal"]))
    story.append(Spacer(1, 12))

    # ---------- EDUCATION ----------
    story.append(Paragraph("<b>Education:</b>", styles["Heading2"]))
    story.append(Paragraph(f"Degree: {academic.get('degree','')}", styles["Normal"]))
    story.append(Paragraph(f"College: {academic.get('college','')}", styles["Normal"]))
    story.append(Paragraph(f"CGPA: {academic.get('cgpa','')}", styles["Normal"]))
    story.append(Spacer(1, 12))

    # ---------- PROJECT ----------
    story.append(Paragraph("<b>Project:</b> " + academic.get("project",""), styles["Normal"]))
    story.append(Spacer(1, 12))

    # ---------- INTERNSHIP ----------
    story.append(Paragraph("<b>Internship:</b> " + academic.get("internship",""), styles["Normal"]))
    story.append(Spacer(1, 18))

    # Build PDF
    doc.build(story)

    # Return PDF
    return FileResponse(pdf_path, media_type="application/pdf", filename=f"{student_id}_resume.pdf")



#  Dashboard Info Endpoint
# ----------------------------
@app.get("/api/dashboard/{student_id}")
def get_dashboard_info(student_id: str):
    """
    Fetch limited student info for dashboard card.
    Includes name, email, department, class (degree), and academic year.
    """

    # Fetch records from MongoDB collections
    personal = personal_collection.find_one({"student_id": student_id}) or {}
    academic = academic_collection.find_one({"student_id": student_id}) or {}
    register = register_collection.find_one({"student_id": student_id}) or {}

    # If no data found
    if not (personal or academic or register):
        raise HTTPException(status_code=404, detail="Student not found")

    # Combine the relevant fields
    dashboard_data = {
        "student_id": student_id,
        "name": personal.get("name", ""),
        "email": personal.get("email", register.get("email", "")),
        "department": academic.get("department", ""),
        "class": academic.get("degree", ""),
        "academic_year": academic.get("year", "")
    }

    return dashboard_data


#.......upload resume

import PyPDF2
import re

def serialize_doc(doc):
    if not doc:
        return doc
    if "_id" in doc:
        doc["_id"] = str(doc["_id"])
    return doc

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)
# ------------------ Extract Text ------------------
def extract_text_from_pdf(pdf_path):
    text = ""
    with open(pdf_path, "rb") as f:
        reader = PyPDF2.PdfReader(f)
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
    return text

# ------------------ Parse Resume ------------------
def parse_resume_text(text):
    # Extract email
    email = re.findall(r'[\w\.-]+@[\w\.-]+', text)

    # Extract phone number
    phone = re.findall(r'\+?\d[\d\s-]{8,12}\d', text)

    # Guess name (first capitalized short line)
    name_match = re.search(r'Name\s*[:\-]\s*(.+)', text, re.IGNORECASE)
    name = name_match.group(1).strip() if name_match else None

    # Skills extraction
    skills_keywords = [
        "Python", "Java", "C++", "C#", "HTML", "CSS", "JavaScript",
        "MongoDB", "SQL", "React", "Node", "Machine Learning", "AI",
        "Data Science", "Django", "Flask", "FastAPI"
    ]
    found_skills = [s for s in skills_keywords if s.lower() in text.lower()]

    
    # ------------------ Marks extraction ------------------
   # SSC / 10th marks (look for % or "10th %:")
    ssc_match = re.search(
    r'(?:10th.*?%|10th.*?:)\s*(\d{1,3}(?:\.\d+)?)', text, re.IGNORECASE)
    ssc_marks = ssc_match.group(1) + "%" if ssc_match else None

# HSC / 12th marks (look for % or "12th %:")
    hsc_match = re.search(
    r'(?:12th.*?%|12th.*?:)\s*(\d{1,3}(?:\.\d+)?)', text, re.IGNORECASE)
    hsc_marks = hsc_match.group(1) + "%" if hsc_match else None

# CGPA / GPA extraction
    cgpa_match = re.search(
    r'(?:CGPA|GPA|Grade Point)[^\d]{0,20}?(\d{1,2}(?:\.\d{1,2})?)', text, re.IGNORECASE)
    cgpa = cgpa_match.group(1) if cgpa_match else None

    # ------------------ Combine parsed data ------------------
    parsed_data = {
        "name": name,
        "email": email[0] if email else None,
        "phone": phone[0] if phone else None,
        "skills": found_skills,
        "ssc_marks": ssc_marks,
        "hsc_marks": hsc_marks,
        "cgpa": cgpa,
    }
    return parsed_data


# ------------------ Upload API ------------------
@app.post("/upload_resume/")
async def upload_resume(file: UploadFile = File(...)):
    try:
        # Ensure uploads directory exists
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        file_path = os.path.join(UPLOAD_DIR, file.filename)

        # Save uploaded file temporarily
        with open(file_path, "wb") as f:
            f.write(await file.read())

        text = extract_text_from_pdf(file_path)
        if not text.strip():
            raise ValueError("No text found in PDF. Ensure it’s not an image-based file.")

        parsed_data = parse_resume_text(text)
        parsed_data["uploaded_at"] = datetime.utcnow()

        # Store parsed data in MongoDB
        resume_parsed_collection.insert_one(parsed_data)

        # Cleanup temporary file
        os.remove(file_path)

        return {
            "success": True,
            "message": "Resume uploaded and parsed successfully!",
            "parsed_data": parsed_data,
        }

    except Exception as e:
        print("⚠️ Resume parsing error:", e)
        return JSONResponse(status_code=500, content={"error": str(e)})

        


# --- Allow frontend to connect ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- API to analyze resume ---
@app.post("/analyze_resume")
async def analyze_resume(resume: UploadFile, job_description: str = Form(...)):
    try:
        os.makedirs("uploads", exist_ok=True)
        file_path = f"uploads/{resume.filename}"

        # Save uploaded resume
        with open(file_path, "wb") as f:
            f.write(await resume.read())

        # Extract text from PDF
        resume_text = extract_text_from_pdf(file_path)

        if not resume_text.strip():
            raise HTTPException(
                status_code=400,
                detail="Resume contains no readable text."
            )

        # -------------------------------
        #  ML similarity score using scikit-learn
        # -------------------------------
        score = compute_similarity(resume_text, job_description)

        # Save result in MongoDB
        record = {
            "filename": resume.filename,
            "job_description": job_description,
            "score": score,
            "uploaded_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        collection.insert_one(record)

        return {
            "score": score,
            "message": "Resume analyzed successfully using scikit-learn"
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))





@app.post("/api/upload_resume")
async def upload_resume(
    prn: str = Form(...),
    resume_file: UploadFile = File(...)
):
    # Read new file data
    file_data = await resume_file.read()

    # Check if resume already stored for this PRN
    existing = db.resumes.find_one({"prn": prn})

    if existing:
        old_file_id = existing["file_id"]

        # Delete old file from GridFS
        fs.delete(old_file_id)

    # Store new file in GridFS
    new_file_id = fs.put(
        file_data,
        filename=resume_file.filename,
        content_type=resume_file.content_type
    )

    # Update resume record in DB
    db.resumes.update_one(
        {"prn": prn},
        {
            "$set": {
                "prn": prn,
                "file_id": new_file_id,
                "filename": resume_file.filename,
                "content_type": resume_file.content_type
            }
        },
        upsert=True
    )

    return {
        "message": "Resume uploaded successfully",
        "updated": True,
        "file_id": str(new_file_id)
    }


@app.get("/api/get_resume/{prn}")
def get_resume(prn: str):
    record = db.resumes.find_one({"prn": prn})
    if not record:
        return {"error": "Resume not found"}

    file_id = record["file_id"]
    file_data = fs.get(file_id)

    return Response(
        content=file_data.read(),
        media_type=file_data.content_type,
        headers={"Content-Disposition": f"attachment; filename={record['filename']}"}
    )


@app.get("/api/students_by_department/{department}")
def students_by_department(department: str):
    """
    Returns list of students in a department with:
    index, prn, name, resume_download_link
    """
    # Fetch students from academic database
    academic_students = list(academic_collection.find(
        {"department": {"$regex": f"^{department}$", "$options": "i"}}
    ))

    result = []

    for index, stu in enumerate(academic_students, start=1):
        student_id = stu.get("student_id")

        # Get personal details
        personal = personal_collection.find_one({"student_id": student_id}) or {}
        prn = personal.get("prn", "N/A")
        name = personal.get("name", "Unknown")

        # Get resume file
        resume_record = db.resumes.find_one({"prn": prn})

        if resume_record:
            resume_link = f"/api/get_resume/{prn}"
        else:
            resume_link = None

        # Prepare list row
        result.append({
            "index": index,
            "prn": prn,
            "name": name,
            "resume": resume_link
        })

    return {
        "department": department.upper(),
        "count": len(result),
        "students": result
    }



def normalize_cgpa(cgpa_value):
    if not cgpa_value:
        return 0.0
    # try common formats: "8.5", "8.5/10", "85%", "80"
    try:
        cgpa_str = str(cgpa_value).strip()
        if "%" in cgpa_str:
            num = float(cgpa_str.replace("%",""))
            return max(0.0, min(100.0, num))  # already percentage
        if "/" in cgpa_str:
            left = cgpa_str.split("/")[0]
            num = float(left)
            # assume scale 10 or 100 based on value
            if num <= 10:
                return (num / 10.0) * 100.0
            return min(100.0, num)
        num = float(cgpa_str)
        # if <=10 treat as CGPA out of 10
        if num <= 10:
            return (num / 10.0) * 100.0
        return min(100.0, num)
    except:
        return 0.0

def compute_hybrid_score(parsed, job_description, academic=None,
                         weights=(0.5,0.35,0.15)):
    """
    parsed: dict from resume_parsed_collection (must include 'skills' list and optional 'text' or other fields)
    job_description: string
    academic: dict from academic_collection (optional, used for cgpa)
    weights: tuple (w_tfidf, w_skills, w_cgpa)
    returns: final_score in 0..100
    """
    # 1) Build resume text for TF-IDF: prefer full parsed text field if exists,
    # else join skills + name + any other parsed fields.
    resume_text = ""
    if parsed.get("text"):
        resume_text = parsed["text"]
    else:
        parts = []
        if parsed.get("name"):
            parts.append(parsed["name"])
        if isinstance(parsed.get("skills"), (list,tuple)):
            parts.append(" ".join(parsed.get("skills")))
        else:
            parts.append(str(parsed.get("skills") or ""))
        # include other short fields if present
        for field in ("ssc_marks","hsc_marks","cgpa","email"):
            if parsed.get(field):
                parts.append(str(parsed.get(field)))
        resume_text = " ".join(parts).strip()

    # TF-IDF similarity
    try:
        vect = TfidfVectorizer(stop_words="english")
        tfidf = vect.fit_transform([resume_text, job_description])
        sim = cosine_similarity(tfidf[0:1], tfidf[1:2])[0][0]
        score_tfidf = float(sim) * 100.0
    except Exception:
        score_tfidf = 0.0

    # Skills overlap (case-insensitive)
    skills_parsed = parsed.get("skills") or []
    if isinstance(skills_parsed, str):
        skills_parsed = [s.strip() for s in skills_parsed.split(",") if s.strip()]
    skills_parsed = [s.lower() for s in skills_parsed if s]
    # derive keywords from job description (split + simple cleaning)
    job_keywords = [k.strip().lower() for k in re.findall(r"\w+", job_description)]
    # count intersection vs union (use individual tokens and skills)
    set_skills = set(skills_parsed)
    set_job = set(job_keywords)
    if not set_skills:
        score_skills = 0.0
    else:
        inter = len(set_skills & set_job)
        union = len(set_skills | (set_job & set_skills)) if (set_job & set_skills) else len(set_skills)
        # safer: overlap ratio = inter / len(set_skills)
        score_skills = (inter / (len(set_skills) if len(set_skills) else 1)) * 100.0

    # CGPA normalization
    cgpa_val = None
    if academic and academic.get("cgpa"):
        cgpa_val = academic.get("cgpa")
    elif parsed.get("cgpa"):
        cgpa_val = parsed.get("cgpa")
    score_cgpa = normalize_cgpa(cgpa_val)  # now in 0..100

    # Weighted sum
    w_tfidf, w_skills, w_cgpa = weights
    final = (w_tfidf * score_tfidf) + (w_skills * score_skills) + (w_cgpa * score_cgpa)
    # clamp
    final = max(0.0, min(100.0, final))
    return round(final, 2)
@app.post("/api/job_matching")
async def job_matching(
    department: str = Form(...),
    job_description: str = Form(...),
    min_cgpa: float = Form(0.0),
    min_ssc: float = Form(0.0),
    min_hsc: float = Form(0.0),
    required_skills: str = Form(""),
):
    """
    Filters students by department, cgpa, ssc, hsc and required skills.
    Computes a simple match percentage based on presence of job description keywords
    in the student's profile text. Returns sorted 'shortlisted' list.
    """
    shortlisted = []

    # defensive normalization
    try:
        department = (department or "").strip()
        job_description = (job_description or "").strip()
        min_cgpa = float(min_cgpa) if min_cgpa is not None else 0.0
        min_ssc = float(min_ssc) if min_ssc is not None else 0.0
        min_hsc = float(min_hsc) if min_hsc is not None else 0.0
    except Exception:
        # If parsing fails, fallback to zeros
        min_cgpa = min_cgpa or 0.0
        min_ssc = min_ssc or 0.0
        min_hsc = min_hsc or 0.0

    # fetch students of that department
    students = academic_collection.find({
        "department": {"$regex": f"^{re.escape(department)}$", "$options": "i"}
    })

    # user required skills set
    user_required = [s.strip().lower() for s in required_skills.split(",") if s.strip()]

    # tokens from JD for simplistic matching
    desc_tokens = [t.lower() for t in re.findall(r"\w+", job_description)]

    for academic in students:
        student_id = academic.get("student_id")
        if not student_id:
            continue

        personal = personal_collection.find_one({"student_id": student_id}) or {}
        other = other_collection.find_one({"student_id": student_id}) or {}

        # ---------- CGPA filter ----------
        raw_cgpa = academic.get("cgpa") or academic.get("score") or 0
        try:
            cgpa_val = float(raw_cgpa)
        except Exception:
            # try to extract numeric from strings like "8.5/10" or "85%"
            try:
                cgpa_val = float(re.findall(r"[\d\.]+", str(raw_cgpa))[0])
            except Exception:
                cgpa_val = 0.0

        # Support cgpa expressed on scale of 10 or 100 (if <=10 assume /10)
        cgpa_numeric = cgpa_val
        if cgpa_numeric <= 10:
            # convert to percentage for comparison of thresholds if user provided cgpa as e.g. 7 (treat as 7.0)
            # but frontend expects CGPA as normal (we compare as-is)
            pass

        # If user provided CGPA threshold as e.g., 7 (keep the same comparison)
        if cgpa_numeric < min_cgpa:
            continue

        # ---------- SSC filter ----------
        ssc_raw = academic.get("xPercentage", academic.get("ssc_marks", "0")) or "0"
        ssc_str = str(ssc_raw).replace("%", "").strip()
        try:
            ssc_val = float(ssc_str)
        except:
            ssc_val = 0.0
        if min_ssc > 0 and ssc_val < min_ssc:
            continue

        # ---------- HSC filter ----------
        hsc_raw = academic.get("xiiPercentage", academic.get("hsc_marks", "0")) or "0"
        hsc_str = str(hsc_raw).replace("%", "").strip()
        try:
            hsc_val = float(hsc_str)
        except:
            hsc_val = 0.0
        if min_hsc > 0 and hsc_val < min_hsc:
            continue

        # ---------- skills filter ----------
        student_skills_raw = other.get("skills", "") or ""
        if isinstance(student_skills_raw, list):
            student_skills = [s.strip().lower() for s in student_skills_raw if s]
        else:
            student_skills = [s.strip().lower() for s in str(student_skills_raw).split(",") if s.strip()]

        if user_required:
            # accept if at least one required skill present
            if not any(req in student_skills for req in user_required):
                continue

        # ---------- match score ----------
        # build text pool from available fields
        text_pool = " ".join([
            str(personal.get("profile_summary", "")),
            str(academic.get("project", "")),
            str(academic.get("internship", "")),
            str(other.get("achievements", "")),
            str(other.get("certifications", ""))
        ]).lower()

        if desc_tokens:
            matched = sum(1 for t in desc_tokens if t in text_pool)
            match_percentage = round((matched / len(desc_tokens)) * 100, 2)
        else:
            match_percentage = 0.0

        shortlisted.append({
            "student_id": student_id,
            "prn": personal.get("prn") or personal.get("student_id") or "",
            "name": personal.get("name") or "",
            "department": academic.get("department") or department,
            "cgpa": cgpa_numeric,
            "skills": student_skills,
            "match_percentage": match_percentage
        })

    # sort by match percentage desc, then cgpa desc
    shortlisted = sorted(shortlisted, key=lambda x: (x.get("match_percentage", 0), x.get("cgpa", 0)), reverse=True)

    return {"department": department, "shortlisted": shortlisted}

@app.get("/api/download_shortlisted_resumes/")
def download_shortlisted_resumes(prns: str):
    """
    prns: comma-separated string of PRNs for shortlisted students
    Example: "23062701242054,23062701242055"
    """
    prn_list = prns.split(",")
    zip_buffer = BytesIO()

    with zipfile.ZipFile(zip_buffer, "w") as zipf:
        for prn in prn_list:
            record = db.resumes.find_one({"prn": prn})
            if record:
                file_id = record["file_id"]
                file_data = fs.get(file_id)
                zipf.writestr(record["filename"], file_data.read())

    zip_buffer.seek(0)
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=shortlisted_resumes.zip"}
    )

@app.get("/api/download_shortlisted_excel/")
def download_shortlisted_excel(prns: str):
    prn_list = prns.split(",")
    data = []

    for prn in prn_list:
        personal = personal_collection.find_one({"prn": prn}) or {}
        academic = academic_collection.find_one({"prn": prn}) or {}
        other = other_collection.find_one({"student_id": personal.get("student_id")}) or {}

        data.append({
            "PRN": prn,
            "Name": personal.get("name", ""),
            "Email": personal.get("email", ""),
            "Phone": personal.get("phone", ""),
            "Department": academic.get("department", ""),
            "CGPA": academic.get("cgpa", ""),
            "Skills": other.get("skills", ""),
            "Hobbies": other.get("hobbies", ""),
            "Achievements": other.get("achievements", "")
        })

    df = pd.DataFrame(data)
    stream = BytesIO()
    df.to_excel(stream, index=False)
    stream.seek(0)

    return StreamingResponse(
        stream,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=shortlisted_students.xlsx"}
    )




# Serve static HTML and CSS files
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")



@app.get("/dashboard")
def serve_dashboard():
    return FileResponse("templates/TPO_dashbord.html")

def compute_similarity(resume_text, job_description):
    documents = [resume_text, job_description]
    vectorizer = TfidfVectorizer(stop_words='english')
    tfidf_matrix = vectorizer.fit_transform(documents)

    # Cosine similarity between resume (0) and job description (1)
    similarity_score = cosine_similarity(tfidf_matrix[0:1], tfidf_matrix[1:2])[0][0]

    # Convert to percentage
    return round(similarity_score * 100, 2)