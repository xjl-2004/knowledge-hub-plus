from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, SmallInteger, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "kh_user"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str] = mapped_column(String(50))
    password: Mapped[str] = mapped_column(String(255))
    email: Mapped[Optional[str]] = mapped_column(String(100))
    real_name: Mapped[Optional[str]] = mapped_column(String(50))
    avatar: Mapped[Optional[str]] = mapped_column(String(500))
    email_verified: Mapped[int] = mapped_column(SmallInteger, default=1)
    status: Mapped[int] = mapped_column(SmallInteger, default=1)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)


class Role(Base):
    __tablename__ = "kh_role"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    role_name: Mapped[str] = mapped_column(String(50))
    role_code: Mapped[str] = mapped_column(String(50))
    description: Mapped[Optional[str]] = mapped_column(String(200))
    status: Mapped[int] = mapped_column(SmallInteger, default=1)


class UserRole(Base):
    __tablename__ = "kh_user_role"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("kh_user.id"))
    role_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("kh_role.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Permission(Base):
    __tablename__ = "kh_permission"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    parent_id: Mapped[int] = mapped_column(BigInteger, default=0)
    permission_name: Mapped[str] = mapped_column(String(50))
    permission_code: Mapped[str] = mapped_column(String(100))
    permission_type: Mapped[int] = mapped_column(SmallInteger)
    menu_url: Mapped[Optional[str]] = mapped_column(String(200))
    api_url: Mapped[Optional[str]] = mapped_column(String(500))
    method: Mapped[Optional[str]] = mapped_column(String(10))
    icon: Mapped[Optional[str]] = mapped_column(String(50))
    sort: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[int] = mapped_column(SmallInteger, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)


class RolePermission(Base):
    __tablename__ = "kh_role_permission"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    role_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("kh_role.id"))
    permission_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("kh_permission.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class UserPermission(Base):
    __tablename__ = "kh_user_permission"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("kh_user.id"))
    permission_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("kh_permission.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Team(Base):
    __tablename__ = "kh_team"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    team_name: Mapped[str] = mapped_column(String(100))
    team_code: Mapped[Optional[str]] = mapped_column(String(50))
    description: Mapped[Optional[str]] = mapped_column(String(500))
    leader_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    parent_id: Mapped[int] = mapped_column(BigInteger, default=0)
    sort: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[int] = mapped_column(SmallInteger, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)


class TeamMember(Base):
    __tablename__ = "kh_team_member"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    team_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("kh_team.id"))
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("kh_user.id"))
    member_role: Mapped[str] = mapped_column(String(20), default="member")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Document(Base):
    __tablename__ = "kh_document"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    title: Mapped[str] = mapped_column(String)
    content_id: Mapped[str] = mapped_column(String, unique=True)
    summary: Mapped[Optional[str]] = mapped_column(String)
    category_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    team_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    author_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    cover_image: Mapped[Optional[str]] = mapped_column(String)
    tags: Mapped[Optional[str]] = mapped_column(String)
    status: Mapped[int] = mapped_column(SmallInteger, default=0)
    remark: Mapped[Optional[str]] = mapped_column(String)
    view_count: Mapped[int] = mapped_column(Integer, default=0)
    like_count: Mapped[int] = mapped_column(Integer, default=0)
    comment_count: Mapped[int] = mapped_column(Integer, default=0)
    favourite_count: Mapped[int] = mapped_column(Integer, default=0)
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    publish_time: Mapped[Optional[datetime]] = mapped_column(DateTime)
    is_public: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    create_by: Mapped[Optional[int]] = mapped_column(BigInteger)
    update_by: Mapped[Optional[int]] = mapped_column(BigInteger)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)


class DocumentReview(Base):
    __tablename__ = "kh_document_review"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    document_id: Mapped[int] = mapped_column(BigInteger)
    reviewer_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    reviewer_name: Mapped[Optional[str]] = mapped_column(String)
    review_result: Mapped[Optional[int]] = mapped_column(SmallInteger)
    review_comment: Mapped[Optional[str]] = mapped_column(String)
    before_status: Mapped[int] = mapped_column(SmallInteger)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AiSession(Base):
    __tablename__ = "kh_ai_session"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger)
    title: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AiMessage(Base):
    __tablename__ = "kh_ai_message"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    session_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("kh_ai_session.id", ondelete="CASCADE")
    )
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    sources: Mapped[Optional[list]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
