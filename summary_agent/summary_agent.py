import os
import logging
from flask import Flask, request, jsonify
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from functools import wraps
from supabase import create_client
import datetime
from dotenv import load_dotenv
from flask_cors import CORS

load_dotenv()

# Import Google Generative AI client
import google.generativeai as genai

# Configure the client
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("summary-agent")

app = Flask(__name__)

FRONTEND_ORIGIN = os.environ.get('FRONTEND_ORIGIN', 'http://localhost:3000')
CORS(app, origins=[
    FRONTEND_ORIGIN,
    'http://localhost:3000'
], supports_credentials=True)

# Initialize Supabase client
supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_ROLE_KEY"))

# Email template HTML with PrepZo colors
EMAIL_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Conversation Summary</title>
    <style>
        /* Base styles */
        body {
            margin: 0;
            padding: 0;
            width: 100% !important;
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            line-height: 1.6;
            color: #333333;
            background-color: #f5f7f5;
            -webkit-text-size-adjust: none;
        }
        table {
            border-spacing: 0;
            border-collapse: collapse;
            mso-table-lspace: 0pt;
            mso-table-rspace: 0pt;
        }
        table td {
            border-collapse: collapse;
        }
        img {
            -ms-interpolation-mode: bicubic;
            border: 0;
            outline: none;
            text-decoration: none;
        }
        /* Responsive styles */
        @media only screen and (max-width: 620px) {
            table[class=container] {
                width: 100% !important;
            }
            table[class=container-padding] {
                padding-left: 12px !important;
                padding-right: 12px !important;
            }
        }
    </style>
</head>
<body style="margin: 0; padding: 0; background-color: #f5f7f5; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; width: 100% !important;">
    <!-- Email Container -->
    <table border="0" cellpadding="0" cellspacing="0" width="100%">
        <tr>
            <td align="center" style="padding: 20px 0;">
                <!-- Email Content -->
                <table class="container" border="0" cellpadding="0" cellspacing="0" width="600" style="background-color: #ffffff; border-radius: 8px; box-shadow: 0 4px 8px rgba(0, 0, 0, 0.1);">
                    <!-- Header -->
                    <tr>
                        <td align="center" style="padding: 20px 0; border-bottom: 1px solid #e0e0e0;">
                            <table border="0" cellpadding="0" cellspacing="0" width="100%">
                                <tr>
                                    <td align="center" style="font-size: 32px; font-weight: bold; color: #1c3724;">
                                        Prepzo<span style="color: #45594c;">.</span>
                                    </td>
                                </tr>
                                <tr>
                                    <td align="center" style="color: #45594c; font-size: 16px;">
                                        Your AI Voice Assistant for Career Guidance
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>
                    
                    <!-- Content -->
                    <tr>
                        <td class="container-padding" style="padding: 20px 30px;">
                            <!-- Conversation Summary Section -->
                            <table border="0" cellpadding="0" cellspacing="0" width="100%">
                                <tr>
                                    <td style="color: #1c3724; font-size: 18px; font-weight: 600; border-bottom: 1px solid #e0e0e0; padding-bottom: 5px;">
                                        Conversation Summary
                                    </td>
                                </tr>
                                <tr>
                                    <td style="padding-top: 15px;">
                                        <table border="0" cellpadding="0" cellspacing="0" width="100%" style="background-color: #f5f7f5; border-radius: 5px; border-left: 4px solid #1c3724;">
                                            <tr>
                                                <td style="padding: 15px; color: #333333;">
                                                    {summary_content}
                                                </td>
                                            </tr>
                                        </table>
                                    </td>
                                </tr>
                            </table>
                            
                            <!-- CTA Button -->
                            <table border="0" cellpadding="0" cellspacing="0" width="100%" style="margin: 25px 0;">
                                <tr>
                                    <td align="center">
                                        <table border="0" cellpadding="0" cellspacing="0">
                                            <tr>
                                                <td align="center" bgcolor="#1c3724" style="border-radius: 6px;">
                                                    <a href="https://prepzo.ai" target="_blank" style="padding: 12px 24px; color: white; text-decoration: none; display: inline-block; font-weight: 600; text-transform: uppercase; font-size: 14px; letter-spacing: 0.5px;">
                                                        CONTINUE YOUR JOURNEY
                                                    </a>
                                                </td>
                                            </tr>
                                        </table>
                                    </td>
                                </tr>
                            </table>
                            
                            <!-- Thank you text -->
                            <table border="0" cellpadding="0" cellspacing="0" width="100%">
                                <tr>
                                    <td style="padding-bottom: 10px;">
                                        Thank you for using our services! This email contains a summary of your recent conversation (Session ID: <span style="color: #1c3724; font-weight: bold;">{session_id}</span>).
                                    </td>
                                </tr>
                                <tr>
                                    <td>
                                        Talk to Prepzo, your AI voice assistant that provides tailored strategies for your professional challenges, job search, and career growth.
                                    </td>
                                </tr>
                            </table>
                            
                            <!-- How Prepzo Can Help You -->
                            <table border="0" cellpadding="0" cellspacing="0" width="100%" style="margin-top: 20px;">
                                <tr>
                                    <td style="color: #1c3724; font-size: 18px; font-weight: 600; border-bottom: 1px solid #e0e0e0; padding-bottom: 5px;">
                                        How Prepzo Can Help You
                                    </td>
                                </tr>
                                
                                <!-- Step 1 -->
                                <tr>
                                    <td style="padding-top: 15px;">
                                        <table border="0" cellpadding="0" cellspacing="0" width="100%">
                                            <tr>
                                                <td width="40" valign="top">
                                                    <table border="0" cellpadding="0" cellspacing="0" width="28" height="28" bgcolor="#1c3724" style="border-radius: 50%; text-align: center;">
                                                        <tr>
                                                            <td valign="middle" align="center" style="color: white; font-weight: bold;">1</td>
                                                        </tr>
                                                    </table>
                                                </td>
                                                <td style="padding-left: 10px;">
                                                    Tailor your resume to specific job requirements
                                                </td>
                                            </tr>
                                        </table>
                                    </td>
                                </tr>
                                
                                <!-- Step 2 -->
                                <tr>
                                    <td style="padding-top: 15px;">
                                        <table border="0" cellpadding="0" cellspacing="0" width="100%">
                                            <tr>
                                                <td width="40" valign="top">
                                                    <table border="0" cellpadding="0" cellspacing="0" width="28" height="28" bgcolor="#1c3724" style="border-radius: 50%; text-align: center;">
                                                        <tr>
                                                            <td valign="middle" align="center" style="color: white; font-weight: bold;">2</td>
                                                        </tr>
                                                    </table>
                                                </td>
                                                <td style="padding-left: 10px;">
                                                    Create personalized cover letters that stand out
                                                </td>
                                            </tr>
                                        </table>
                                    </td>
                                </tr>
                                
                                <!-- Step 3 -->
                                <tr>
                                    <td style="padding-top: 15px;">
                                        <table border="0" cellpadding="0" cellspacing="0" width="100%">
                                            <tr>
                                                <td width="40" valign="top">
                                                    <table border="0" cellpadding="0" cellspacing="0" width="28" height="28" bgcolor="#1c3724" style="border-radius: 50%; text-align: center;">
                                                        <tr>
                                                            <td valign="middle" align="center" style="color: white; font-weight: bold;">3</td>
                                                        </tr>
                                                    </table>
                                                </td>
                                                <td style="padding-left: 10px;">
                                                    Prepare for interviews with industry-specific questions
                                                </td>
                                            </tr>
                                        </table>
                                    </td>
                                </tr>
                            </table>
                            
                            <!-- FAQ Section -->
                            <table border="0" cellpadding="0" cellspacing="0" width="100%" style="margin-top: 20px;">
                                <tr>
                                    <td style="color: #1c3724; font-size: 18px; font-weight: 600; border-bottom: 1px solid #e0e0e0; padding-bottom: 5px;">
                                        Frequently Asked Questions
                                    </td>
                                </tr>
                                
                                <!-- FAQ 1 -->
                                <tr>
                                    <td style="padding-top: 15px;">
                                        <table border="0" cellpadding="0" cellspacing="0" width="100%">
                                            <tr>
                                                <td style="font-weight: 600; color: #1c3724; padding-bottom: 5px;">
                                                    How long is the demo session?
                                                </td>
                                            </tr>
                                            <tr>
                                                <td>
                                                    The free demo session is 10 minutes long, giving you enough time to experience Prepzo's capabilities.
                                                </td>
                                            </tr>
                                        </table>
                                    </td>
                                </tr>
                                
                                <!-- FAQ 2 -->
                                <tr>
                                    <td style="padding-top: 15px;">
                                        <table border="0" cellpadding="0" cellspacing="0" width="100%">
                                            <tr>
                                                <td style="font-weight: 600; color: #1c3724; padding-bottom: 5px;">
                                                    Is the demo really free?
                                                </td>
                                            </tr>
                                            <tr>
                                                <td>
                                                    Yes, no credit card required. Start your free demo now.
                                                </td>
                                            </tr>
                                        </table>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>
                    
                    <!-- Footer -->
                    <tr>
                        <td align="center" style="padding-top: 20px; border-top: 1px solid #e0e0e0; color: #45594c; font-size: 14px;">
                            <table border="0" cellpadding="0" cellspacing="0" width="100%">
                                <tr>
                                    <td align="center" style="padding: 0 30px 10px 30px;">
                                        &copy; 2025 Prepzo.ai | All Rights Reserved
                                    </td>
                                </tr>
                                <tr>
                                    <td align="center" style="padding: 0 30px 15px 30px;">
                                        Your AI voice assistant for personalized career guidance and professional development
                                    </td>
                                </tr>
                                <tr>
                                    <td align="center" style="padding: 0 30px 20px 30px;">
                                        <a href="#" style="color: #1c3724; text-decoration: none; margin: 0 8px;">LinkedIn</a>
                                        <a href="#" style="color: #1c3724; text-decoration: none; margin: 0 8px;">Twitter</a>
                                        <a href="#" style="color: #1c3724; text-decoration: none; margin: 0 8px;">Instagram</a>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
</body>
</html>"""

def generate_summary(conversation):
    try:
        formatted_conv = "\n".join(
            f"{msg['role'].capitalize()}: {msg['content']}"
            for msg in conversation if msg.get("content")
        )
        prompt = (
            "Summarize this conversation into 5-10 key bullet points. "
            "Keep it concise and professional. "
            "EXCLUDE any tool calls, tool results, or system-generated messages.You have to consider on;ly those messages having user or assistant as role."
            "Focus solely on the key interactions between the user and the assistant. "
            "Here is the conversation:\n\n"
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
                    # Add bullet point styling compatible with email clients
                    formatted_summary += f'<li style="margin-bottom: 10px; color: #333333;">{line.strip()}</li>\n'
            summary = f'<ul style="margin: 5px 0; padding-left: 20px;">\n{formatted_summary}</ul>'
        else:
            # If summary already has bullets, convert to HTML with styling
            summary_items = []
            for line in summary.strip().split('\n'):
                if line.strip():
                    # Remove existing bullet points and add styled HTML bullets
                    cleaned_line = line.strip()
                    if cleaned_line.startswith('•') or cleaned_line.startswith('-'):
                        cleaned_line = cleaned_line[1:].strip()
                    summary_items.append(f'<li style="margin-bottom: 10px; color: #333333;">{cleaned_line}</li>')
            
            summary = f'<ul style="margin: 5px 0; padding-left: 20px;">\n' + '\n'.join(summary_items) + '\n</ul>'
        
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
        
        test_session_id = "test-session-12356"
        
        email_content = generate_email_content(test_summary, test_session_id)
        send_summary_email(test_email, email_content, test_session_id)
        
        return jsonify({"status": "success", "detail": f"Test email sent to {test_email}"})
    
    except Exception as e:
        logger.error(f"Test email failed: {str(e)}")
        return jsonify({"status": "error", "detail": str(e)}), 500


@app.route("/sendsummary", methods=["POST"])
def send_summary():
    try:
        payload = request.get_json()
        
        if not payload or "room_id" not in payload:
            logger.error("Missing room_id in request")
            return jsonify({"status": "bad request"}), 400
            
        session_id = payload["room_id"]
        logger.info(f"Received summary request for session {session_id}")
        
        # Get user email from database
        email_response = supabase.table("user_emails") \
            .select("email") \
            .eq("session_id", session_id) \
            .execute()
            
        if not email_response.data:
            logger.error(f"No email found for session {session_id}")
            return jsonify({"status": "not found"}), 404
            
        email = email_response.data[0]["email"]
        
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
        logger.error(f"Summary processing failed: {str(e)}")
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