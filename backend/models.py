from sqlalchemy import Boolean, Column, Integer, String, DateTime, Float, Text, ForeignKey
from datetime import datetime
from database import Base


class User(Base):
    __tablename__ = "users"

    id              = Column(Integer, primary_key=True, index=True)
    clerk_user_id   = Column(String, unique=True, index=True, nullable=False)  # Clerk's user_id
    email           = Column(String, index=True, nullable=True)
    full_name       = Column(String, nullable=True)
    # Where the user SENDS FROM — the country they live or study in, and the
    # country their university is in. ISO 2-letter, e.g. "GB".
    country         = Column(String, nullable=True)
    university      = Column(String, nullable=True)
    whatsapp_number = Column(String, nullable=True)    # E.164, e.g. "+447700900123"
    home_currency   = Column(String, nullable=True)    # currency they send home to, e.g. "INR"
    corridor_from   = Column(String, nullable=True)    # currency of `country`, e.g. "GBP"
    corridor_to     = Column(String, nullable=True)    # e.g. "INR" — never equal to corridor_from
    is_onboarded    = Column(Boolean, default=False)
    created_at      = Column(DateTime, default=datetime.utcnow)
    updated_at      = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Comparison(Base):
    __tablename__ = "comparisons"

    id            = Column(Integer, primary_key=True, index=True)
    clerk_user_id = Column(String, ForeignKey("users.clerk_user_id", ondelete="CASCADE"), nullable=True)
    amount        = Column(Float, nullable=False)
    from_currency = Column(String, nullable=False)
    to_currency   = Column(String, nullable=False)
    results_json  = Column(Text, nullable=False)   # JSON-serialised results snapshot
    created_at    = Column(DateTime, default=datetime.utcnow)


class RateAlert(Base):
    __tablename__ = "rate_alerts"

    id              = Column(Integer, primary_key=True, index=True)
    clerk_user_id   = Column(String, ForeignKey("users.clerk_user_id", ondelete="CASCADE"), nullable=False)
    from_currency   = Column(String, nullable=False)
    to_currency     = Column(String, nullable=False)
    amount          = Column(Float, nullable=False)
    target_rate     = Column(Float, nullable=False)
    provider        = Column(String, nullable=True)   # None = any provider
    # None = any rail. Lets an alert mean "when Wise's UPI rate hits X" rather
    # than "when some rail of some provider does".
    pay_out_method  = Column(String, nullable=True)
    notify_email    = Column(Boolean, default=True)
    notify_whatsapp = Column(Boolean, default=False)
    is_active       = Column(Boolean, default=True)
    last_triggered  = Column(DateTime, nullable=True)
    created_at      = Column(DateTime, default=datetime.utcnow)


class ProviderClick(Base):
    __tablename__ = "provider_clicks"

    id            = Column(Integer, primary_key=True, index=True)
    clerk_user_id = Column(String, nullable=True)          # null = anonymous visitor
    provider      = Column(String, nullable=False, index=True)
    from_currency = Column(String, nullable=False)
    to_currency   = Column(String, nullable=False)
    amount        = Column(Float, nullable=False)
    created_at    = Column(DateTime, default=datetime.utcnow)
