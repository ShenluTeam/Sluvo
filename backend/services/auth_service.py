from __future__ import annotations

import base64
import hashlib
import html
import random
import smtplib
import ssl
import string
import time
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict

import requests
import xmltodict
from fastapi import HTTPException, Request, Response
from sqlmodel import Session, select

from core.config import settings
from core.security import get_password_hash, verify_password
from models import EmailVerificationCode, PointLog, Team, TeamMemberLink, User
from services.storage_service import ensure_user_storage_namespace

captcha_sessions: Dict[str, Any] = {}
login_sessions: Dict[str, Any] = {}
EMAIL_CODE_RESEND_COOLDOWN = timedelta(minutes=1)
EMAIL_CODE_TTL = timedelta(minutes=5)
EMAIL_CODE_PURPOSE_REGISTER = "register"
EMAIL_CODE_PURPOSE_PASSWORD_RESET = "password_reset"
PASSWORD_RESET_GENERIC_MESSAGE = "如果该邮箱已注册，验证码将发送到对应邮箱"


def generate_svg_captcha(code: str) -> str:
    width = 120
    height = 40
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">'
    svg += f'<rect width="100%" height="100%" fill="#{random.randint(0xdddddd, 0xffffff):06x}" />'
    for _ in range(5):
        x1, y1 = random.randint(0, width), random.randint(0, height)
        x2, y2 = random.randint(0, width), random.randint(0, height)
        svg += f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="#{random.randint(0xaaaaaa, 0xcccccc):06x}" stroke-width="{random.randint(1, 3)}" />'
    for _ in range(30):
        cx, cy = random.randint(0, width), random.randint(0, height)
        svg += f'<circle cx="{cx}" cy="{cy}" r="{random.random()*1.5}" fill="#{random.randint(0x888888, 0xbbbbbb):06x}" />'
    for i, char in enumerate(code):
        x = 20 + i * 20 + random.randint(-2, 2)
        y = 28 + random.randint(-4, 4)
        rotate = random.randint(-20, 20)
        color = f"#{random.randint(0x111111, 0x777777):06x}"
        svg += f'<text x="{x}" y="{y}" fill="{color}" font-size="24" font-weight="bold" font-family="Arial, sans-serif" transform="rotate({rotate}, {x}, {y})">{char}</text>'
    svg += "</svg>"
    return svg


def get_captcha_payload() -> dict:
    now = time.time()
    expired_keys = [k for k, v in captcha_sessions.items() if v["expire_at"] < now]
    for key in expired_keys:
        del captcha_sessions[key]
    chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    code = "".join(random.choice(chars) for _ in range(4))
    session_id = str(uuid.uuid4())
    captcha_sessions[session_id] = {"code": code.lower(), "expire_at": now + 300}
    svg_data = generate_svg_captcha(code)
    b64_img = base64.b64encode(svg_data.encode("utf-8")).decode("utf-8")
    return {"captcha_id": session_id, "image": f"data:image/svg+xml;base64,{b64_img}"}


def validate_captcha(captcha_id: str, captcha_code: str) -> None:
    if not captcha_id or not captcha_code:
        raise HTTPException(status_code=400, detail="请输入图形验证码")
    captcha_data = captcha_sessions.get(captcha_id)
    if not captcha_data:
        raise HTTPException(status_code=400, detail="图形验证码已过期或无效，请刷新")
    if captcha_data["code"] != captcha_code.lower():
        raise HTTPException(status_code=400, detail="图形验证码输入错误")
    captcha_sessions.pop(captcha_id, None)


def send_verification_email(to_email: str, code: str, *, purpose: str = EMAIL_CODE_PURPOSE_REGISTER) -> None:
    msg_obj = __import__("email.mime.multipart", fromlist=["MIMEMultipart"]).MIMEMultipart("alternative")
    mime_text = __import__("email.mime.text", fromlist=["MIMEText"]).MIMEText
    msg_obj["From"] = f"神鹿AI <{settings.SMTP_SENDER_EMAIL}>"
    msg_obj["To"] = to_email
    is_password_reset = purpose == EMAIL_CODE_PURPOSE_PASSWORD_RESET
    email_title = "重置密码验证码" if is_password_reset else "邮箱验证码"
    email_intro = "请使用下方验证码重置你的神鹿AI账号密码。" if is_password_reset else "请使用下方验证码完成账号注册或邮箱验证。"
    plain_action = "重置密码" if is_password_reset else "注册验证码"
    logo_url = f"{str(settings.OPENCLAW_PUBLIC_BASE_URL or settings.SHENLU_AGENT_API_BASE_URL or 'https://ai.shenlu.top').rstrip('/')}/logo.png"
    resend_hint_html = (
        '<p style="margin:20px 0 0;font-size:13px;line-height:1.8;color:#5c4932;">验证码可以在 1 分钟后重新发送；重新发送后，旧验证码将失效。</p>'
        if is_password_reset
        else ""
    )
    msg_obj["Subject"] = f"神鹿AI - {email_title}"
    safe_code = html.escape(code)
    display_code = " ".join(safe_code)
    plain_body = f"【神鹿AI】您的{plain_action}是：{code}，该验证码 5 分钟内有效。如非本人操作请忽略。"
    html_body = f"""<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>神鹿AI {email_title}</title>
  </head>
  <body style="margin:0;padding:0;background:#f7f1e6;color:#2d2114;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',Arial,sans-serif;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f7f1e6;padding:32px 16px;">
      <tr>
        <td align="center">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:560px;background:#fffaf1;border:1px solid #d8c8ae;border-radius:20px;overflow:hidden;box-shadow:0 20px 44px rgba(99,69,39,0.14);">
            <tr>
              <td style="padding:30px 32px 18px;background:linear-gradient(135deg,#fffaf1 0%,#f5ead8 100%);">
                <div style="display:flex;align-items:center;gap:10px;">
                  <img src="{logo_url}" width="36" height="36" alt="神鹿AI" style="display:block;width:36px;height:36px;border-radius:12px;border:1px solid rgba(216,200,174,0.72);object-fit:cover;">
                  <div style="font-size:13px;font-weight:700;letter-spacing:0.12em;color:#2563eb;text-transform:uppercase;">Shenlu AI</div>
                </div>
                <h1 style="margin:10px 0 0;font-size:24px;line-height:1.35;color:#2d2114;">{email_title}</h1>
                <p style="margin:10px 0 0;font-size:14px;line-height:1.8;color:#5c4932;">{email_intro}</p>
              </td>
            </tr>
            <tr>
              <td style="padding:18px 32px 28px;">
                <div style="border:1px solid rgba(37,99,235,0.18);border-radius:18px;background:#ffffff;padding:24px;text-align:center;">
                  <div style="font-size:12px;font-weight:700;color:#7b6850;">验证码</div>
                  <div style="margin:12px 0 10px;font-size:40px;line-height:1;font-weight:800;letter-spacing:0.18em;color:#1d4ed8;font-family:'SFMono-Regular',Consolas,'Liberation Mono',monospace;">{display_code}</div>
                  <div style="display:inline-block;margin-top:4px;padding:7px 12px;border-radius:999px;background:rgba(249,115,22,0.12);color:#a7773f;font-size:12px;font-weight:700;">5 分钟内有效</div>
                </div>
                {resend_hint_html}
                <p style="margin:8px 0 0;font-size:13px;line-height:1.8;color:#7b6850;">如果这不是你本人的操作，请忽略这封邮件。</p>
              </td>
            </tr>
            <tr>
              <td style="padding:18px 32px 28px;background:#f5ead8;border-top:1px solid #eadcc6;">
                <div style="font-size:12px;line-height:1.7;color:#7b6850;">神鹿AI · AI 漫剧 / 短剧创作平台</div>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>"""
    msg_obj.attach(mime_text(plain_body, "plain", "utf-8"))
    msg_obj.attach(mime_text(html_body, "html", "utf-8"))
    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT, context=context) as server:
        server.login(settings.SMTP_SENDER_EMAIL, settings.SMTP_SENDER_PASSWORD)
        server.send_message(msg_obj)


def issue_email_code(session: Session, *, email: str, captcha_id: str, captcha_code: str) -> dict:
    validate_captcha(captcha_id, captcha_code)
    existing_user = session.exec(select(User).where(User.email == email)).first()
    if existing_user and existing_user.email_verified:
        raise HTTPException(status_code=400, detail="该邮箱已被注册")
    now = datetime.utcnow()
    recent = session.exec(
        select(EmailVerificationCode)
        .where(EmailVerificationCode.email == email)
        .where(EmailVerificationCode.purpose == EMAIL_CODE_PURPOSE_REGISTER)
        .order_by(EmailVerificationCode.created_at.desc())
    ).first()
    if recent and (now - recent.created_at) < EMAIL_CODE_RESEND_COOLDOWN:
        raise HTTPException(status_code=400, detail="发送过于频繁，请 1 分钟后再试")
    code = "".join(random.choice(string.digits) for _ in range(6))
    session.add(EmailVerificationCode(email=email, code=code, purpose=EMAIL_CODE_PURPOSE_REGISTER, expire_at=now + EMAIL_CODE_TTL))
    send_verification_email(email, code, purpose=EMAIL_CODE_PURPOSE_REGISTER)
    session.commit()
    return {"msg": "验证码已发送"}


def register_user(session: Session, request: Request, *, email: str, password: str, email_code: str, nickname: str | None) -> dict:
    db_code = session.exec(
        select(EmailVerificationCode)
        .where(EmailVerificationCode.email == email)
        .where(EmailVerificationCode.purpose == EMAIL_CODE_PURPOSE_REGISTER)
        .order_by(EmailVerificationCode.created_at.desc())
    ).first()
    if not db_code or db_code.code != email_code or db_code.expire_at < datetime.utcnow():
        raise HTTPException(status_code=400, detail="邮箱验证码无效或已过期")
    if session.exec(select(User).where(User.email == email)).first():
        raise HTTPException(status_code=400, detail="该邮箱已被注册")
    if nickname and session.exec(select(User).where(User.nickname == nickname)).first():
        raise HTTPException(status_code=400, detail="该用户名已被注册")

    final_nickname = nickname or f"神鹿用户_{str(uuid.uuid4())[:6]}"
    client_ip = request.client.host if request.client else None
    user = User(
        email=email,
        hashed_password=get_password_hash(password),
        nickname=final_nickname,
        email_verified=True,
        register_ip=client_ip,
        last_login_ip=client_ip,
        permanent_points=50,
    )
    team = Team(name=f"{final_nickname} 的制作组")
    session.add(user)
    session.add(team)
    session.commit()
    session.refresh(user)
    session.refresh(team)
    ensure_user_storage_namespace(session, int(user.id))
    link = TeamMemberLink(team_id=team.id, user_id=user.id, role="admin")
    session.add(link)
    session.add(PointLog(
        user_id=user.id,
        change_amount=50,
        balance_after=50,
        action_type="registration_bonus",
        description="新用户注册赠送 50 点永久灵感值",
    ))
    session.commit()
    return {"status": "success", "msg": "注册成功"}


def issue_password_reset_code(session: Session, *, email: str, captcha_id: str, captcha_code: str) -> dict:
    validate_captcha(captcha_id, captcha_code)
    user = session.exec(select(User).where(User.email == email)).first()
    if not user or not user.is_active:
        return {"msg": PASSWORD_RESET_GENERIC_MESSAGE}
    now = datetime.utcnow()
    recent = session.exec(
        select(EmailVerificationCode)
        .where(EmailVerificationCode.email == email)
        .where(EmailVerificationCode.purpose == EMAIL_CODE_PURPOSE_PASSWORD_RESET)
        .order_by(EmailVerificationCode.created_at.desc())
    ).first()
    if recent and (now - recent.created_at) < EMAIL_CODE_RESEND_COOLDOWN:
        raise HTTPException(status_code=400, detail="发送过于频繁，请 1 分钟后再试")
    code = "".join(random.choice(string.digits) for _ in range(6))
    session.add(EmailVerificationCode(
        email=email,
        code=code,
        purpose=EMAIL_CODE_PURPOSE_PASSWORD_RESET,
        expire_at=now + EMAIL_CODE_TTL,
    ))
    send_verification_email(email, code, purpose=EMAIL_CODE_PURPOSE_PASSWORD_RESET)
    session.commit()
    return {"msg": PASSWORD_RESET_GENERIC_MESSAGE}


def confirm_password_reset(session: Session, *, email: str, email_code: str, new_password: str) -> dict:
    user = session.exec(select(User).where(User.email == email)).first()
    db_code = session.exec(
        select(EmailVerificationCode)
        .where(EmailVerificationCode.email == email)
        .where(EmailVerificationCode.purpose == EMAIL_CODE_PURPOSE_PASSWORD_RESET)
        .order_by(EmailVerificationCode.created_at.desc())
    ).first()
    if not user or not user.is_active or not db_code or db_code.code != email_code or db_code.expire_at < datetime.utcnow():
        raise HTTPException(status_code=400, detail="邮箱验证码无效或已过期")
    user.hashed_password = get_password_hash(new_password)
    user.session_token = None
    user.email_verified = True
    session.add(user)
    session.commit()
    return {"status": "success", "msg": "密码已重置，请使用新密码登录"}


def login_user(session: Session, request: Request, *, email: str, password: str) -> dict:
    user = session.exec(select(User).where(User.email == email)).first()
    if not user or not verify_password(password, user.hashed_password):
        raise HTTPException(status_code=400, detail="邮箱或密码错误")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="该账号已被封禁，请联系客服")
    user.last_login_ip = request.client.host if request.client else None
    user.last_login_at = datetime.utcnow()
    user.session_token = str(uuid.uuid4())
    session.add(user)
    session.commit()
    return {
        "status": "success",
        "token": user.session_token,
        "nickname": user.nickname,
        "email": user.email,
        "email_verified": user.email_verified,
    }


def verify_email_code(session: Session, user: User, email_code: str) -> dict:
    db_code = session.exec(
        select(EmailVerificationCode)
        .where(EmailVerificationCode.email == user.email)
        .where(EmailVerificationCode.purpose == EMAIL_CODE_PURPOSE_REGISTER)
        .order_by(EmailVerificationCode.created_at.desc())
    ).first()
    if not db_code or db_code.code != email_code or db_code.expire_at < datetime.utcnow():
        raise HTTPException(status_code=400, detail="邮箱验证码无效或已过期")
    user.email_verified = True
    session.add(user)
    session.commit()
    return {"status": "success", "msg": "邮箱验证成功"}


def get_wechat_access_token() -> str | None:
    url = f"https://api.weixin.qq.com/cgi-bin/token?grant_type=client_credential&appid={settings.WECHAT_APPID}&secret={settings.WECHAT_SECRET}"
    return requests.get(url).json().get("access_token")


def create_wechat_login_session() -> dict:
    access_token = get_wechat_access_token()
    if not access_token:
        raise HTTPException(status_code=500, detail="无法获取微信 AccessToken")
    scene_str = uuid.uuid4().hex
    url = f"https://api.weixin.qq.com/cgi-bin/qrcode/create?access_token={access_token}"
    payload = {"expire_seconds": 300, "action_name": "QR_STR_SCENE", "action_info": {"scene": {"scene_str": scene_str}}}
    resp = requests.post(url, json=payload).json()
    if "ticket" not in resp:
        raise HTTPException(status_code=500, detail=f"生成二维码失败: {resp}")
    login_sessions[scene_str] = {"status": "pending", "session_token": None}
    return {"scene_str": scene_str, "qrcode_url": f"https://mp.weixin.qq.com/cgi-bin/showqrcode?ticket={resp['ticket']}"}


def check_wechat_login(scene_str: str) -> dict:
    session_data = login_sessions.get(scene_str)
    if not session_data:
        return {"status": "expired"}
    if session_data["status"] == "success":
        token = session_data["session_token"]
        login_sessions.pop(scene_str, None)
        return {"status": "success", "token": token}
    return {"status": "pending"}


def verify_wechat_webhook(signature: str, timestamp: str, nonce: str, echostr: str) -> Response:
    tmp_list = [settings.WECHAT_TOKEN, timestamp, nonce]
    tmp_list.sort()
    tmp_str = "".join(tmp_list)
    sign = hashlib.sha1(tmp_str.encode("utf-8")).hexdigest()
    if sign == signature:
        return Response(content=echostr, media_type="text/plain")
    return Response(content="error", media_type="text/plain")


def handle_wechat_webhook(request_xml: bytes, session: Session) -> Response:
    try:
        msg = xmltodict.parse(request_xml).get("xml", {})
    except Exception:
        return Response(content="success", media_type="text/plain")
    msg_type = msg.get("MsgType")
    event = msg.get("Event")
    openid = msg.get("FromUserName")
    event_key = msg.get("EventKey", "")
    if msg_type == "event" and event in ["subscribe", "SCAN"]:
        scene_str = event_key.replace("qrscene_", "") if event_key.startswith("qrscene_") else event_key
        if scene_str in login_sessions:
            user = session.exec(select(User).where(User.wechat_openid == openid)).first()
            if not user:
                user = User(wechat_openid=openid, nickname=f"用户_{openid[-4:]}", permanent_points=50)
                session.add(user)
                session.commit()
                session.refresh(user)
                ensure_user_storage_namespace(session, int(user.id))
                session.add(PointLog(
                    user_id=user.id,
                    change_amount=50,
                    balance_after=50,
                    action_type="registration_bonus",
                    description="新用户关注赠送 50 点永久灵感值",
                ))
                session.commit()
            user.session_token = str(uuid.uuid4())
            session.add(user)
            session.commit()
            login_sessions[scene_str]["status"] = "success"
            login_sessions[scene_str]["session_token"] = user.session_token
            reply_xml = f"""
            <xml>
              <ToUserName><![CDATA[{openid}]]></ToUserName>
              <FromUserName><![CDATA[{msg.get('ToUserName')}]]></FromUserName>
              <CreateTime>{int(time.time())}</CreateTime>
              <MsgType><![CDATA[text]]></MsgType>
              <Content><![CDATA[欢迎登录神鹿影视 AI，网页端已自动跳转。]]></Content>
            </xml>
            """
            return Response(content=reply_xml, media_type="application/xml")
    return Response(content="success", media_type="text/plain")
