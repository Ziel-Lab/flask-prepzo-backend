import os
import logging
from flask import Flask, request, jsonify
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from functools import wraps
from supabase import create_client
import datetime

# Import Google Generative AI client
import google.generativeai as genai

# Configure the client
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("summary-agent")

app = Flask(__name__)

# Initialize Supabase client
supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

# Email template HTML with PrepZo colors
EMAIL_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Conversation Summary</title>
    <style>
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            line-height: 1.6;
            color: #f9f9f9;
            margin: 0;
            padding: 0;
            background-color: #121212;
        }
        .container {
            max-width: 600px;
            margin: 0 auto;
            padding: 20px;
            background-color: #1e1e1e;
            border-radius: 8px;
            box-shadow: 0 4px 8px rgba(0, 0, 0, 0.2);
        }
        .header {
            text-align: center;
            padding: 20px 0;
            border-bottom: 1px solid #333;
        }
        .logo {
            font-size: 32px;
            font-weight: bold;
            color: #ffffff;
            margin-bottom: 5px;
        }
        .logo span {
            color: #a675f5;
        }
        .title {
            color: #ffffff;
            font-size: 28px;
            font-weight: 600;
            margin-bottom: 5px;
        }
        .subtitle {
            color: #a0a0a0;
            font-size: 16px;
            margin-top: 0;
        }
        .content {
            padding: 20px 0;
        }
        .section-title {
            color: #ffffff;
            font-size: 18px;
            font-weight: 600;
            margin-bottom: 15px;
            border-bottom: 1px solid #333;
            padding-bottom: 5px;
        }
        .summary {
            background-color: #252525;
            padding: 15px;
            border-radius: 5px;
            border-left: 4px solid #a675f5;
            color: #ffffff; /* Ensuring text is white */
        }
        .summary ul {
            padding-left: 20px;
            margin: 10px 0;
        }
        .summary li {
            margin-bottom: 10px;
            color: #ffffff; /* Ensuring bullet points are white */
        }
        .button-container {
            text-align: center;
            margin: 25px 0;
        }
        .button {
            display: inline-block;
            padding: 12px 24px;
            background-color: #a675f5;
            color: white;
            text-decoration: none;
            border-radius: 6px;
            font-weight: 600;
            text-transform: uppercase;
            font-size: 14px;
            letter-spacing: 0.5px;
            transition: background-color 0.3s;
        }
        .button:hover {
            background-color: #9161e3;
        }
        .footer {
            text-align: center;
            padding-top: 20px;
            border-top: 1px solid #333;
            color: #a0a0a0;
            font-size: 14px;
        }
        .social-links {
            margin-top: 15px;
        }
        .social-link {
            display: inline-block;
            margin: 0 8px;
            color: #a675f5;
            text-decoration: none;
        }
        .highlight {
            color: #a675f5;
            font-weight: bold;
        }
        /* Ensure all text has sufficient contrast */
        p {
            color: #ffffff;
        }
        /* Style for bullet points specifically */
        .summary ul li::marker {
            color: #a675f5; /* Purple bullet points */
        }
        .summary ul li {
            padding-left: 5px; /* Add some space after bullet */
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="logo">prepzo<span>.</span></div>
            <p class="subtitle">Your AI-Powered Career Coach</p>
        </div>
        
        <div class="content">
            <h2 class="section-title">Conversation Summary</h2>
            <div class="summary">
                {summary_content}
            </div>
            
            <div class="button-container">
                <a href="https://prepzo.ai" class="button">✨ CONTINUE YOUR JOURNEY ✨</a>
            </div>
            
            <p>Thank you for using our services! This email contains a summary of your recent conversation (Session ID: <span class="highlight">{session_id}</span>).</p>
            <p>Embark on a journey of professional growth with an AI coach that understands, remembers, and evolves with YOU.</p>
        </div>
        
        <div class="footer">
            <p>&copy; 2025 Prepzo.ai | All Rights Reserved</p>
            <p>Your AI-Powered Career Coach</p>
            <div class="social-links">
                <a href="#" class="social-link">Twitter</a>
                <a href="#" class="social-link">LinkedIn</a>
                <a href="#" class="social-link">Instagram</a>
            </div>
        </div>
    </div>
</body>
</html>"""

def generate_summary(conversation):
    try:
        formatted_conv = "\n".join(
            f"{msg['role'].capitalize()}: {msg['content']}"
            for msg in conversation if msg.get("content")
        )
        prompt = (
            "Summarize this conversation into 3-5 key bullet points. "
            "Keep it concise and professional. Here is the conversation:\n\n"
            f"{formatted_conv}"
        )
        model = genai.GenerativeModel('gemini-2.0-flash')
        response = model.generate_content(prompt, generation_config=genai.types.GenerationConfig(temperature=0.2))
        summary = response.text
        return summary

    except Exception as e:
        logger.error(f"Summary generation failed: {str(e)}")
        raise

def generate_email_content(summary, session_id):
    try:
        # Format the summary with bullet points if not already formatted
        if not summary.strip().startswith('•') and not summary.strip().startswith('-'):
            summary_lines = summary.strip().split('\n')
            formatted_summary = ''
            for line in summary_lines:
                if line.strip():
                    # Add some styling to each bullet point to ensure visibility
                    formatted_summary += f'<li style="color: #ffffff; margin-bottom: 10px;">{line.strip()}</li>\n'
            summary = f'<ul style="color: #ffffff; padding-left: 20px;">\n{formatted_summary}</ul>'
        else:
            # If summary already has bullets, convert to HTML with styling
            summary_items = []
            for line in summary.strip().split('\n'):
                if line.strip():
                    # Remove existing bullet points and add styled HTML bullets
                    cleaned_line = line.strip()
                    if cleaned_line.startswith('•') or cleaned_line.startswith('-'):
                        cleaned_line = cleaned_line[1:].strip()
                    summary_items.append(f'<li style="color: #ffffff; margin-bottom: 10px;">{cleaned_line}</li>')
            
            summary = f'<ul style="color: #ffffff; padding-left: 20px;">\n' + '\n'.join(summary_items) + '\n</ul>'
        
        # Replace placeholders with actual content
        email_content = EMAIL_TEMPLATE.replace('{summary_content}', summary)
        email_content = email_content.replace('{session_id}', session_id[:8])
        
        return email_content

    except Exception as e:
        logger.error(f"Email content generation failed: {str(e)}")
        # Fallback to generating content with AI if template fails
        return generate_email_content_with_ai(summary, session_id)
    
def generate_email_content_with_ai(summary, session_id):
    try:
        prompt = (
            "Generate a professional HTML email body that includes the following conversation summary "
            f"for session {session_id}. The email should have a header with Prepzo.ai branding using dark theme with purple accent colors (#a675f5), "
            "a section with bullet points (do not use * in text output) for the summary, a button to visit prepzo.ai, "
            "and a courteous closing note. Return only the HTML content.\n\nSummary:\n"
            f"{summary}"
        )
        model = genai.GenerativeModel('gemini-2.0-flash')
        response = model.generate_content(prompt, generation_config=genai.types.GenerationConfig(temperature=0.2))
        html_content = response.text
        return html_content

    except Exception as e:
        logger.error(f"AI email content generation failed: {str(e)}")
        raise

def send_summary_email(email, email_content, session_id):
    try:
        smtp_server = "smtp.gmail.com"
        smtp_port = 587
        gmail_user = os.getenv("GMAIL_USER", '')
        gmail_password = os.getenv("GMAIL_PASSWORD", '')

        logger.info(f"GMAIL_USER: {gmail_user}")
        logger.info(f"GMAIL_PASSWORD: {'*' * len(gmail_password) if gmail_password else None}")

        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"Prepzo.ai - Conversation Summary - {session_id[:8]}"
        msg["From"] = f"Prepzo.ai Assistant <{gmail_user}>"
        msg["To"] = email

        part = MIMEText(email_content, "html")
        msg.attach(part)

        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(gmail_user, gmail_password)
        server.sendmail(gmail_user, email, msg.as_string())
        server.quit()
        logger.info(f"Email sent to {email}")

        # Log success to Supabase email_logs table
        current_time = datetime.datetime.now().isoformat()
        log_data = {
            "session_id": session_id,
            "email": email,
            "status": "sent",
            "timestamp": current_time,
            "subject": f"Prepzo.ai - Conversation Summary - {session_id[:8]}",
            "html_content": email_content
        }
        
        try:
            supabase.table("email_logs").insert(log_data).execute()
            logger.info(f"Email log saved to database for session {session_id}")
        except Exception as e:
            logger.error(f"Failed to log email in database: {str(e)}")

    except Exception as e:
        logger.error(f"Email send failed: {str(e)}")
        
        # Log failure to Supabase email_logs table
        current_time = datetime.datetime.now().isoformat()
        log_data = {
            "session_id": session_id,
            "email": email,
            "status": "failed",
            "error": str(e),
            "timestamp": current_time,
            "subject": f"Prepzo.ai - Conversation Summary ",
            "html_content": email_content if 'email_content' in locals() else None
        }
        
        try:
            supabase.table("email_logs").insert(log_data).execute()
            logger.info(f"Email failure log saved to database for session {session_id}")
        except Exception as log_err:
            logger.error(f"Failed to log email error in database: {str(log_err)}")
            
        raise

WEBHOOK_SECRET ='**************************'
# os.getenv("WEBHOOK_SECRET")

def validate_webhook(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Verify secret token
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            logger.warning("Missing or invalid Authorization header")
            return jsonify({"status": "unauthorized"}), 401
            
        received_secret = auth_header.split(" ")[1]
        if received_secret != WEBHOOK_SECRET:
            logger.warning("Invalid webhook secret")
            return jsonify({"status": "unauthorized"}), 401
            
        # Verify content type
        if request.content_type != 'application/json':
            logger.warning("Invalid content type")
            return jsonify({"status": "unsupported media type"}), 415
            
        return f(*args, **kwargs)
    return decorated_function

@app.route("/webhook/email-added", methods=["POST"])
@validate_webhook
def handle_email_webhook():
    try:
        payload = request.get_json()
        logger.info(f"Received valid webhook payload")
        
        # Validate payload structure
        if not payload or "record" not in payload:
            logger.error("Invalid payload structure")
            return jsonify({"status": "bad request"}), 400
            
        record = payload["record"]
        required_fields = ["session_id", "email"]
        
        if not all(field in record for field in required_fields):
            logger.error("Missing required fields in payload")
            return jsonify({"status": "bad request"}), 400
            
        session_id = record["session_id"]
        email = record["email"]
        
        # Get conversation history
        conv_response = supabase.table("conversation_histories") \
            .select("conversation") \
            .eq("session_id", session_id) \
            .execute()

        if not conv_response.data:
            logger.error(f"No conversation found for session {session_id}")
            return jsonify({"status": "not found"}), 404

        # Generate and send summary
        conversation = conv_response.data[0]["conversation"]
        summary = generate_summary(conversation)
        email_content = generate_email_content(summary, session_id)
        
        send_summary_email(email, email_content, session_id)
        return jsonify({"status": "success"})

    except Exception as e:
        logger.error(f"Webhook processing failed: {str(e)}")
        return jsonify({"status": "error", "detail": str(e)}), 500

@app.route("/test-email", methods=["GET"])
def test_email():
    """Endpoint to test email functionality"""
    try:
        test_email = request.args.get("email")
        if not test_email:
            return jsonify({"status": "error", "detail": "Email parameter required"}), 400
        
        test_summary = """• The user discussed their goals for career advancement in the technology sector.
• They expressed interest in improving their leadership and communication skills.
• The assistant provided personalized guidance on skill development and networking strategies.
• The user requested resources for interview preparation and resume enhancement."""
        
        test_session_id = "test-session-123456"
        
        email_content = generate_email_content(test_summary, test_session_id)
        send_summary_email(test_email, email_content, test_session_id)
        
        return jsonify({"status": "success", "detail": f"Test email sent to {test_email}"})
    
    except Exception as e:
        logger.error(f"Test email failed: {str(e)}")
        return jsonify({"status": "error", "detail": str(e)}), 500

required_env_vars = [
    "SUPABASE_URL", "SUPABASE_KEY",
    "GOOGLE_API_KEY",
]

missing_vars = [var for var in required_env_vars if not os.getenv(var)]
if missing_vars:
    logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")
    exit(1)

if __name__ == "__main__":
    # Validate all required environment variables are set
    if missing_vars:
        logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")
        exit(1)
        
    app.run(host="0.0.0.0", port=8000, ssl_context='adhoc' if os.getenv("FLASK_ENV") == "production" else None)