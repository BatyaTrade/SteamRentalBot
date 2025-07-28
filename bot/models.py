# bot/models.py
from sqlalchemy import Column, Integer, String, DECIMAL, DateTime, Boolean, BigInteger, Text, ForeignKey, Numeric
from sqlalchemy.dialects.postgresql import BYTEA
from sqlalchemy.orm import relationship
from bot.database import Base
from datetime import datetime
import uuid

class Owner(Base):
    __tablename__ = "owners"

    id = Column(Integer, primary_key=True, index=True)
    tg_id = Column(BigInteger, unique=True, nullable=False, index=True)
    subscription_end = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    balance = Column(DECIMAL(10, 2), default=0.0, nullable=False)
    funpay_user_id_encrypted = Column(BYTEA, nullable=True)
    funpay_golden_key_encrypted = Column(BYTEA, nullable=True)

    funpay_accounts = relationship("FunPayAccount", back_populates="owner", cascade="all, delete-orphan")
    steam_accounts = relationship("Account", back_populates="owner_rel")
    transactions = relationship("Transaction", back_populates="owner_rel")

    def is_subscribed(self) -> bool:
        if not self.subscription_end:
            return False
        return self.subscription_end > datetime.utcnow()

    def has_funpay_credentials(self) -> bool:
        return self.funpay_user_id_encrypted is not None and self.funpay_golden_key_encrypted is not None

    def __repr__(self):
        return f"<Owner(id={self.id}, tg_id={self.tg_id}, subscribed={self.is_subscribed()})>"

class FunPayAccount(Base):
    __tablename__ = "funpay_accounts"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey('owners.id'), nullable=False)
    name = Column(String(100), nullable=False)
    user_id_encrypted = Column(BYTEA, nullable=False)
    golden_key_encrypted = Column(BYTEA, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

    owner_rel = relationship("Owner", back_populates="funpay_accounts")
    steam_accounts = relationship("Account", back_populates="funpay_account_rel")

    def __repr__(self):
        return f"<FunPayAccount(id={self.id}, name='{self.name}', owner_id={self.owner_id})>"

class Account(Base): # Steam Account
    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True, index=True)
    owner_tg_id = Column(BigInteger, ForeignKey('owners.tg_id'), nullable=False) # Внешний ключ на Owner.tg_id
    funpay_account_id = Column(Integer, ForeignKey('funpay_accounts.id'), nullable=True)
    
    login = Column(String(64), unique=True, nullable=False, index=True)
    base_password_encrypted = Column(BYTEA, nullable=False) # BYTEA для бинарных данных
    shared_secret_encrypted = Column(BYTEA, nullable=False)
    current_password = Column(String(64), nullable=True) # Хранится в открытом виде, действует только во время аренды
    price_per_hour = Column(DECIMAL(10, 2), nullable=False) # DECIMAL для точности денег
    status = Column(String(20), default='available', nullable=False) # available, rented, blocked
    renter_username = Column(String(64), nullable=True)
    rent_end_time = Column(DateTime, nullable=True)
    max_rental_duration = Column(Integer, nullable=True) # Макс. время аренды в часах
    allowed_regions = Column(Text, nullable=True) # JSON или просто текст
    game_limits = Column(Text, nullable=True) # JSON или просто текст

    owner_rel = relationship("Owner", back_populates="steam_accounts")
    funpay_account_rel = relationship("FunPayAccount", back_populates="steam_accounts")
    transactions = relationship("Transaction", back_populates="account_rel")

    def __repr__(self):
        return f"<Account(id={self.id}, login='{self.login}', status='{self.status}')>"

class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_tg_id = Column(BigInteger, ForeignKey('owners.tg_id'), nullable=False)
    account_id = Column(Integer, ForeignKey('accounts.id'), nullable=True)
    
    transaction_type = Column(String(20), nullable=False) # 'rental', 'topup', 'subscription'
    external_id = Column(String(64), nullable=True) # ID заказа FunPay или платежа YooKassa
    
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)
    amount = Column(DECIMAL(10, 2), nullable=False) # DECIMAL для точности денег
    status = Column(String(20), default='completed', nullable=False) # 'pending', 'completed', 'failed'

    owner_rel = relationship("Owner", back_populates="transactions")
    account_rel = relationship("Account", back_populates="transactions")

    def __repr__(self):
        return f"<Transaction(id='{self.id}', type='{self.transaction_type}', amount={self.amount})>"
