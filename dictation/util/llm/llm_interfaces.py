"""
LLM interface definitions

Component interfaces defined with Protocol, for dependency inversion
"""
from typing import Protocol, List, Dict, Optional, Tuple, Any
from abc import ABC, abstractmethod


# ======================================================================
# --- Client interface ---

class LLMClient(Protocol):
    """LLM client interface"""

    def chat(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        max_tokens: Optional[int] = None,
        stop: Optional[List[str]] = None,
        stream: bool = False,
        **kwargs
    ) -> Any:
        """Chat call"""
        ...


# ======================================================================
# --- Context management interface ---

class IContextManager(Protocol):
    """Context manager interface"""

    def add_message(self, role: str, content: str) -> None:
        """Add a message to the history"""
        ...

    def get_history(self) -> List[Dict[str, str]]:
        """Return the conversation history"""
        ...


# ======================================================================
# --- RAG interface ---

class IRAG(Protocol):
    """RAG search interface"""

    def search(self, text: str, top_k: int = 5) -> List[Tuple[str, float]]:
        """Search for related content"""
        ...

    def format_prompt(self, text: str) -> str:
        """Build the prompt text"""
        ...


# ======================================================================
# --- Message building interface ---

class IMessageBuilder(Protocol):
    """Message builder interface"""

    def build_messages(
        self,
        role_config: Any,
        text: str,
        context_manager: Optional[IContextManager] = None
    ) -> List[Dict[str, str]]:
        """Build the message list"""
        ...


# ======================================================================
# --- Role loading interface ---

class IRoleLoader(Protocol):
    """Role loader interface"""

    def get_roles(self) -> Dict[str, Any]:
        """Return all roles"""
        ...

    def get_default_role(self) -> Any:
        """Return the default role"""
        ...

    def reload_role(self, file_path: str) -> Tuple[bool, Optional[str]]:
        """Reload one role"""
        ...

    def load_all_roles(self) -> List[Dict[str, Any]]:
        """Load all roles"""
        ...


# ======================================================================
# --- Abstract base classes (for implementations) ---

class AbstractContextManager(ABC):
    """Context manager base class"""

    @abstractmethod
    def add_message(self, role: str, content: str) -> None:
        """Add a message to the history"""
        pass

    @abstractmethod
    def get_history(self) -> List[Dict[str, str]]:
        """Return the conversation history"""
        pass


class AbstractRAG(ABC):
    """RAG search base class"""

    @abstractmethod
    def search(self, text: str, top_k: int = 5) -> List[Tuple[str, float]]:
        """Search for related content"""
        pass

    @abstractmethod
    def format_prompt(self, text: str) -> str:
        """Build the prompt text"""
        pass


class AbstractMessageBuilder(ABC):
    """Message builder base class"""

    @abstractmethod
    def build_messages(
        self,
        role_config: Any,
        text: str,
        context_manager: Optional[IContextManager] = None
    ) -> List[Dict[str, str]]:
        """Build the message list"""
        pass
