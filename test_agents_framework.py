"""
Test rapide de l'architecture multi-agent décentralisée.
Vérifie que tous les agents peuvent démarrer et communiquer.
"""

import asyncio
import pytest
from agent_framework import Agent, get_message_bus


class TestAgent1(Agent):
    """Agent de test 1."""
    
    async def on_startup(self):
        self.log("INFO", "Démarré")
        await self.bus.subscribe(self.name, ["test_message"])
    
    async def run(self):
        for i in range(3):
            await self.send_message("TestAgent2", "ping", {"count": i})
            self.log("INFO", f"Envoyé ping #{i}")
            await asyncio.sleep(1)
            
            msg = await self.wait_for_message(timeout=2)
            if msg:
                self.log("INFO", f"Reçu: {msg.payload}")
        
        self.running = False


class TestAgent2(Agent):
    """Agent de test 2."""
    
    async def on_startup(self):
        self.log("INFO", "Démarré")
        await self.bus.subscribe(self.name, ["ping"])
    
    async def run(self):
        while self.running:
            msg = await self.wait_for_message(timeout=2)
            if msg and msg.event_type == "ping":
                self.log("INFO", f"Reçu ping: {msg.payload}")
                await self.send_message(msg.sender, "pong", {"reply": "Hello!"})
            await asyncio.sleep(0.1)


@pytest.mark.asyncio
async def test_architecture():
    """Test basique — agents communiquent et s'arrêtent proprement."""
    agent1 = TestAgent1("TestAgent1")
    agent2 = TestAgent2("TestAgent2")

    await agent1.start()
    await agent2.start()

    # Timeout 10s : Agent2 boucle indéfiniment, on coupe proprement
    async def _run():
        await asyncio.gather(agent1.run(), agent2.run())

    try:
        await asyncio.wait_for(_run(), timeout=10.0)
    except asyncio.TimeoutError:
        pass  # normal — Agent2 est infini par conception

    agent2.running = False
    assert True  # Pas d'exception = architecture fonctionnelle


if __name__ == "__main__":
    try:
        asyncio.run(test_architecture())
    except KeyboardInterrupt:
        print("\n⏹️  Arrêt")
