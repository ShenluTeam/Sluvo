from fastapi import APIRouter, Depends, Request
from sqlmodel import Session

from database import get_session
from dependencies import get_current_user
from schemas import (
    PasswordResetConfirmRequest,
    PasswordResetSendCodeRequest,
    SendEmailCodeRequest,
    UserLogin,
    UserRegister,
    VerifyEmailRequest,
)
from services import auth_service

router = APIRouter()


@router.get("/api/captcha")
async def get_captcha():
    return auth_service.get_captcha_payload()


@router.post("/api/auth/send-email-code")
async def send_email_code(req: SendEmailCodeRequest, session: Session = Depends(get_session)):
    return auth_service.issue_email_code(
        session,
        email=req.email,
        captcha_id=req.captcha_id,
        captcha_code=req.captcha_code,
    )


@router.post("/api/auth/register")
async def register(req: UserRegister, request: Request, session: Session = Depends(get_session)):
    return auth_service.register_user(
        session,
        request,
        email=req.email,
        password=req.password,
        email_code=req.email_code,
        nickname=req.nickname,
    )


@router.post("/api/auth/password-reset/send-code")
async def send_password_reset_code(req: PasswordResetSendCodeRequest, session: Session = Depends(get_session)):
    return auth_service.issue_password_reset_code(
        session,
        email=req.email,
        captcha_id=req.captcha_id,
        captcha_code=req.captcha_code,
    )


@router.post("/api/auth/password-reset/confirm")
async def confirm_password_reset(req: PasswordResetConfirmRequest, session: Session = Depends(get_session)):
    return auth_service.confirm_password_reset(
        session,
        email=req.email,
        email_code=req.email_code,
        new_password=req.new_password,
    )


@router.post("/api/auth/login")
async def login(req: UserLogin, request: Request, session: Session = Depends(get_session)):
    return auth_service.login_user(session, request, email=req.email, password=req.password)


@router.post("/api/auth/verify-email")
async def verify_email(
    req: VerifyEmailRequest,
    user=Depends(get_current_user),
    session: Session = Depends(get_session),
):
    return auth_service.verify_email_code(session, user, req.email_code)


@router.get("/api/wechat/login_qrcode")
async def get_login_qrcode():
    return auth_service.create_wechat_login_session()


@router.get("/api/wechat/check_login")
async def check_login_status(scene_str: str):
    return auth_service.check_wechat_login(scene_str)


@router.get("/api/wechat/webhook")
async def wechat_webhook_verify(signature: str, timestamp: str, nonce: str, echostr: str):
    return auth_service.verify_wechat_webhook(signature, timestamp, nonce, echostr)


@router.post("/api/wechat/webhook")
async def wechat_webhook_receive(request: Request, session: Session = Depends(get_session)):
    return auth_service.handle_wechat_webhook(await request.body(), session)
