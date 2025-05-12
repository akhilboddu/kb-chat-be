from setuptools import setup, find_packages

setup(
    name="chatwise-be",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "fastapi==0.105.0",
        "uvicorn==0.24.0",
        "pydantic==2.5.2",
        "langchain==0.0.350",
        "langchain-core==0.1.0",
        "langchain-community==0.0.15",
        "langchain-openai==0.0.2",
        "chromadb==0.4.18",
        "pymupdf==1.23.7",
        "pymupdf4llm==0.0.4",
        "pdfplumber==0.10.3",
        "python-docx==1.1.0",
        "python-multipart==0.0.6",
        "requests==2.31.0",
        "beautifulsoup4==4.12.2",
        "openai==1.6.1",
        "httpx==0.25.2",
        "supabase==2.0.0",
        "aiosqlite==0.19.0",
        "pytesseract==0.3.10",
        "python-dotenv==1.0.0",
        "Pillow==10.1.0",
        "tiktoken==0.5.2",
        "pypandoc==1.12",
    ],
    extras_require={
        "test": [
            "pytest==7.4.3",
            "pytest-asyncio==0.21.1",
            "httpx==0.25.2",
            "pytest-cov",
        ],
    },
    python_requires=">=3.9",
)

