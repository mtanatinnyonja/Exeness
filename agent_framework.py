"""
Framework de base pour tous les agents IA.
Chaque agent tourne de manière indépendante et autonome.
"""

import asyncio
import json
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, asdict

_HB_FILE = Path("data/agents_heartbeat.json")


@dataclass
class Message:
    """Message asynchrone entre agents."""
    id: str
    sender: str
    recipient: str  # "*" = broadcast
    event_type: str  # "signal", "decision", "execution", "alert"
    payload: Dict[str, Any]
    timestamp: str = None
    
    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict):
        return cls(**data)


class MessageBus:
    """Bus asynchrone centralisé pour communication entre agents."""
    
    def __init__(self):
        self.queues: Dict[str, asyncio.Queue] = {}  # agent_name -> queue
        self.subscribers: Dict[str, List[str]] = {}  # event_type -> [agent_names]
    
    async def subscribe(self, agent_name: str, event_types: List[str]):
        """S'abonner à des types d'événements."""
        if agent_name not in self.queues:
            self.queues[agent_name] = asyncio.Queue()
        for event_type in event_types:
            if event_type not in self.subscribers:
                self.subscribers[event_type] = []
            if agent_name not in self.subscribers[event_type]:
                self.subscribers[event_type].append(agent_name)
    
    async def send(self, message: Message):
        """Envoie un message."""
        # Broadcast si recipient = "*"
        if message.recipient == "*":
            recipients = self.subscribers.get(message.event_type, [])
            for agent_name in recipients:
                if agent_name == message.sender:
                    continue
                queue = self.queues.get(agent_name)
                if queue is not None:
                    await queue.put(message)
        else:
            # Direct si recipient spécifié
            if message.recipient in self.queues:
                await self.queues[message.recipient].put(message)
            else:
                print(
                    f"[MessageBus] Message perdu: destinataire '{message.recipient}' introuvable "
                    f"(de {message.sender}, événement '{message.event_type}')"
                )
    
    async def receive(self, agent_name: str, timeout: float = 1.0) -> Optional[Message]:
        """Reçoit un message avec timeout."""
        if agent_name not in self.queues:
            self.queues[agent_name] = asyncio.Queue()
        try:
            message = await asyncio.wait_for(
                self.queues[agent_name].get(),
                timeout=timeout
            )
            return message
        except asyncio.TimeoutError:
            return None


# Singleton global
_bus = None


def get_message_bus() -> MessageBus:
    global _bus
    if _bus is None:
        _bus = MessageBus()
    return _bus


class Agent(ABC):
    """Classe de base pour tous les agents autonomes."""
    
    def __init__(self, name: str):
        self.name = name
        self.bus = get_message_bus()
        self.running = False
        self.message_counter = 0
    
    @abstractmethod
    async def on_startup(self):
        """Initialisation de l'agent."""
        pass
    
    @abstractmethod
    async def run(self):
        """Boucle principale autonome de l'agent."""
        pass
    
    async def start(self):
        """Démarre l'agent."""
        self.running = True
        await self.on_startup()
    
    async def stop(self):
        """Arrête l'agent."""
        self.running = False
    
    async def send_message(self, recipient: str, event_type: str, payload: Dict[str, Any]):
        """Envoie un message à un autre agent ou broadcast."""
        self.message_counter += 1
        message = Message(
            id=f"{self.name}_{self.message_counter}",
            sender=self.name,
            recipient=recipient,
            event_type=event_type,
            payload=payload
        )
        await self.bus.send(message)
    
    async def wait_for_message(self, timeout: float = 1.0) -> Optional[Message]:
        """Attend un message."""
        return await self.bus.receive(self.name, timeout)

    def write_heartbeat(self, extra: Optional[Dict] = None):
        """Met à jour le heartbeat de cet agent dans data/agents_heartbeat.json."""
        try:
            _HB_FILE.parent.mkdir(exist_ok=True)
            hb = {}
            if _HB_FILE.exists():
                try:
                    hb = json.loads(_HB_FILE.read_text(encoding="utf-8"))
                except Exception:
                    hb = {}
            entry = {
                "status": "running",
                "last_seen": datetime.now(timezone.utc).isoformat(),
            }
            if extra:
                entry.update(extra)
            hb[self.name] = entry
            _HB_FILE.write_text(json.dumps(hb, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    def log(self, level: str, message: str):
        """Log standardisé."""
        timestamp = datetime.now(timezone.utc).isoformat()
        print(f"[{timestamp}] {level:8s} | {self.name:20s} | {message}")
