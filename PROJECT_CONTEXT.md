# Multi-Tenant AI Sales Agent Backend - Project Context

## Overview

This is a sophisticated multi-tenant AI sales agent backend built with FastAPI that enables businesses to create custom AI sales agents powered by their own knowledge bases. The system supports multiple LLM providers (Google Gemini, DeepSeek, OpenAI), features intelligent web scraping, file processing, conversation management, real-time chat, WhatsApp Business API integration, payment processing, email notifications, and comprehensive human handoff capabilities.

**🚀 Active Migration**: The system is currently migrating from ChromaDB to Supabase Vector DB with Contextual RAG (Retrieval-Augmented Generation) for enhanced knowledge base performance. See [Migration Status](#migration-status) below.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                                FastAPI Application                                      │
├─────────────────────────────────────────────────────────────────────────────────────────┤
│ API Routes: /agents, /chat, /files, /scrape, /bots, /whatsapp, /payments, /status, /ws │
├─────────────────────────────────────────────────────────────────────────────────────────┤
│                                Core Components                                          │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌───────────┐ ┌─────────────┐ ┌──────┐ │
│  │ KB Manager  │ │ DB Manager  │ │Agent Manager│ │ Scraper   │ │ WebSocket   │ │Redis │ │
│  │ (Supabase)  │ │(Supabase+SQL│ │ (LangChain) │ │(Playwright)│ │ Chat Server │ │Status│ │
│  └─────────────┘ └─────────────┘ └─────────────┘ └───────────┘ └─────────────┘ └──────┘ │
├─────────────────────────────────────────────────────────────────────────────────────────┤
│                                Data Storage                                             │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────────────────────┐ ┌─────────────┐        │
│  │ Supabase    │ │  Supabase   │ │        SQLite               │ │   Redis     │        │
│  │ Vector DB   │ │• Conversations│ │ • Agent config             │ │• Bot Status │        │
│  │• Embeddings │ │• Messages    │ │ • Local metadata           │ │• User Status│        │
│  │• Contextual │ │• User Auth   │ │ • Development data         │ │• Sessions   │        │
│  │  RAG        │ │• CRM Data    │ │                            │ │             │        │
│  │• Hybrid     │ │• Integrations│ │                            │ │             │        │
│  │  Search     │ │              │ │                            │ │             │        │
│  └─────────────┘ └─────────────┘ └─────────────────────────────┘ └─────────────┘        │
├─────────────────────────────────────────────────────────────────────────────────────────┤
│                                External Services                                        │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌───────────┐ ┌─────────────┐ ┌──────┐ │
│  │Google Gemini│ │  DeepSeek   │ │   OpenAI    │ │ WhatsApp  │ │  AWS SES    │ │PayStack │
│  │    LLM      │ │    LLM      │ │    LLM      │ │Business API│ │Email Service│ │Payment│ │
│  └─────────────┘ └─────────────┘ └─────────────┘ └───────────┘ └─────────────┘ └──────┘ │
│  ┌─────────────┐ ┌─────────────┐                                                         │
│  │   Cohere    │ │  Anthropic  │                                                         │
│  │ Embeddings  │ │Claude (CTX) │                                                         │
│  └─────────────┘ └─────────────┘                                                         │
└─────────────────────────────────────────────────────────────────────────────────────────┘
```

## Migration Status

### 🔄 ChromaDB → Supabase Vector DB Migration
The system is actively migrating from ChromaDB to Supabase Vector DB with Contextual RAG implementation:

**Completed ✅**
- Dependencies updated (removed ChromaDB, added Cohere + Anthropic)
- Docker configurations updated
- Supabase vector schema with 1024-dim vectors (Cohere)
- Hybrid search function (55% vector + 45% BM25)
- Cohere embeddings wrapper with batch processing
- Contextualizer with Anthropic Claude + OpenAI fallback
- Supabase KB Manager implementation
- Factory module for backward compatibility (`kb_manager_factory.py`)

**In Progress 🔄**
- Remove all legacy ChromaDB code paths
- Data migration script to backfill historical Chroma collections into Supabase

**Remaining 📋**
- End-to-end testing
- Documentation updates

## Core Components

### 1. Knowledge Base Manager (~~`kb_manager.py`~~ → `supabase_kb_manager.py`) 🔄 MIGRATING

**Purpose**: Manages vector-based knowledge storage ~~using ChromaDB~~ **now using Supabase Vector DB** for semantic search and retrieval with Contextual RAG.

**Key Features**:
- **Multi-tenant Collections**: Each agent gets its own ~~ChromaDB collection~~ **Supabase namespace** identified by `kb_id`
- **Embedding-based Storage**: ~~Uses HuggingFace Sentence Transformers (`all-MiniLM-L6-v2`)~~ **Now uses Cohere `embed-english-v3.0`** for text embeddings (1024 dimensions)
- **Contextual RAG**: Implements Anthropic's Contextual Retrieval approach for 40% better retrieval accuracy
- **Hybrid Search**: Combines vector similarity (55%) with BM25 keyword search (45%) for optimal results
- **Text Chunking**: Automatically chunks large text into manageable pieces for better retrieval
- **Context Generation**: Each chunk gets a 50-100 token context summary using Claude 3 Haiku
- **Metadata Support**: Stores metadata with documents (source, timestamps, etc.)
- **Duplicate Detection**: Can identify and remove duplicate content
- **LRU Caching**: Caches context generation to reduce API costs by 90%

**Core Methods**:
```python
create_or_get_kb(kb_id, name=None)  # Create/retrieve KB collection
add_to_kb(kb_id, text, metadata=None)  # Add text with contextual enhancement
get_similar_docs(kb_id, query, n_results=5)  # Hybrid search with optional reranking
cleanup_duplicates(kb_id)  # Remove duplicate documents
```

**New Dependencies**:
- **Cohere**: For embeddings (1024-dim) and optional reranking
- **Anthropic**: For context generation (Claude 3 Haiku)
- **Supabase**: Vector storage with pgvector extension

**Core Methods**:
```python
create_or_get_kb(kb_id, name=None)  # Create/retrieve KB collection
add_to_kb(kb_id, text, metadata=None)  # Add text with contextual enhancement
get_similar_docs(kb_id, query, n_results=5)  # Hybrid search with optional reranking
cleanup_duplicates(kb_id)  # Remove duplicate documents
```

### 2. Database Manager (`db_manager.py`)

**Purpose**: Handles SQLite-based metadata storage for conversations, configurations, and operational data.

**Database Schema**:
- `conversation_history`: Stores chat messages with types (human/ai/human_agent)
- `uploaded_files`: File metadata and upload tracking
- `json_payloads`: Original JSON data used to populate KBs
- `kb_update_log`: Tracks human-verified knowledge additions
- `agent_config`: Per-agent configuration (system prompts, max iterations)
- `scraping_status`: Background scraping operation status

**Key Features**:
- **Conversation Persistence**: Full chat history with timestamps
- **File Tracking**: Metadata for all uploaded files
- **Configuration Management**: Per-agent customizable settings
- **Audit Logging**: Tracks KB updates and changes

### 3. Agent Manager (`agent_manager.py`)

**Purpose**: Creates and manages LangChain-based ReAct agents with conversation memory.

**Agent Architecture**:
- **ReAct Pattern**: Reasoning and Acting loop with tools
- **Conversation Memory**: Persistent chat history loaded from SQLite
- **Dynamic Configuration**: Per-agent system prompts and settings
- **Tool Integration**: Knowledge base retrieval and optional KB updates
- **Error Handling**: Graceful handling of parsing errors and timeouts
- **Enhanced Executor**: Custom wrapper with timeout handling and improved error messages

**Agent Persona**:
- **"TOM"**: Friendly, enthusiastic sales team member
- **Sales-Focused**: Guides users toward purchases and sign-ups
- **Knowledgeable**: Uses KB retrieval to answer questions accurately
- **Human Handoff**: Triggers human intervention with `(needs help)` marker

### 4. File Parser (`file_parser.py`)

**Purpose**: Extracts text content from various file formats for knowledge base population.

**Supported Formats**:
- **PDF**: Uses PyMuPDF for text extraction with Markdown formatting
- **DOCX**: Microsoft Word document parsing
- **TXT/MD**: Plain text and Markdown files
- **CSV**: Spreadsheet data with cell joining
- **XLSX**: Excel spreadsheet parsing

**Features**:
- **Smart Extraction**: Different parsing strategies per file type
- **Error Handling**: Graceful failure with detailed error messages
- **Metadata Tracking**: File size, type, and upload timestamps

### 5. Web Scraper (`scraper.py`)

**Purpose**: Intelligent web scraping using Playwright for automated knowledge base population.

**Key Features**:
- **Multi-page Scraping**: Follows internal links up to configurable limits
- **Content Extraction**: Focuses on main content areas (articles, main content)
- **Business Profile Generation**: LLM-powered extraction of business information
- **Pricing Detection**: Specialized extraction of pricing information
- **Social Media Links**: Automatic discovery of social media profiles
- **Duplicate Detection**: Avoids scraping similar content
- **Progress Tracking**: Real-time status updates during scraping

**Scraping Process**:
1. **Page Analysis**: Extract main content and links
2. **Content Processing**: Clean and structure extracted text
3. **LLM Analysis**: Generate structured business profile
4. **KB Population**: Add processed content to knowledge base

### 6. Real-time WebSocket Chat System

**Purpose**: Provides real-time bidirectional communication for live chat experiences.

**Key Features**:
- **WebSocket Endpoints**: Live chat connections for users and agents
- **Connection Management**: Active connection tracking and broadcasting
- **Message Threading**: Support for reply-to functionality
- **Multi-user Support**: Multiple users can connect to same conversation
- **Agent Notifications**: Real-time alerts for human agents
- **Connection Persistence**: Handles reconnections and connection drops

**WebSocket Endpoints**:
- `/ws/{conversation_id}` - User chat connections
- `/ws/agent/{conversation_id}` - Agent/operator connections
- Real-time message broadcasting to all connected clients

### 7. Online Status Management (Redis)

**Purpose**: Tracks real-time online/offline status of bots and users.

**Key Features**:
- **Bot Status Tracking**: Monitor if bots are actively managed
- **User Status Tracking**: Track user presence per bot
- **Redis Integration**: Fast in-memory status storage
- **TTL Management**: Automatic status expiry handling
- **Email Triggers**: Offline status triggers email notifications

**Status Operations**:
```python
set_bot_online(bot_id)  # Mark bot as online
get_bot_status(bot_id)  # Check if bot is online
set_user_online(user_email, bot_id)  # Mark user as online
get_user_status(user_email, bot_id)  # Check user status
```

## Data Storage Architecture

### Supabase (Primary Database)
- **Database**: PostgreSQL hosted on Supabase
- **Tables**: 
  - `conversations` - Chat conversations with users
  - `messages` - Individual chat messages with roles (user/bot/human)
  - `bots` - Bot configurations and metadata
  - `demo_bots` - Demo bot instances for website demos
  - `whatsapp_configs` - WhatsApp Business API integration settings
  - `bot_crms` - Customer relationship management data
  - `anon_push_subscriptions` - Push notification subscriptions
  - `knowledge_sources` - Tracking of knowledge base sources
  - `users` - User authentication and profile data
  - `subscriptions` - Payment and subscription management
  - `handover_requests` - Human handoff tracking
- **Features**: Real-time subscriptions, authentication, row-level security
- **Connection**: PostgreSQL connection pool for high performance

### SQLite (Legacy/Local Metadata)
- **Location**: `./db/kb_metadata.sqlite`
- **Tables**: 7 main tables for agent configuration and some metadata
- **Usage**: Primarily for agent configurations and local development
- **Backup**: File-based, easily portable

### Redis (Status & Session Management)
- **Purpose**: Real-time status tracking and session management
- **Data Structures**: Key-value pairs with TTL
- **Usage**: Bot online status, user presence, WebSocket session management
- **Expiry**: Automatic cleanup of stale status data

## Supabase Integration Deep Dive

### Core Supabase Features
The system heavily leverages Supabase for:

#### 1. **User Authentication & Authorization**
- **JWT Token Verification**: Bearer token authentication for API endpoints
- **User Management**: Registration, login, and session management
- **Row-Level Security**: Database-level access control
- **User Profiles**: Extended user data and preferences

#### 2. **Real-time Chat System**
- **Conversations Table**: Stores chat sessions with metadata (status, customer info, timestamps)
- **Messages Table**: Individual messages with roles (user/bot/human), read status, and threading
- **Live Updates**: Real-time message synchronization across clients
- **Multi-channel Support**: Web widget, WhatsApp, and direct API access
- **Message Threading**: Support for reply-to functionality
- **Read Receipts**: Track message read status

#### 3. **WhatsApp Business Integration**
- **WhatsApp Configs**: Store access tokens, phone number IDs, webhook settings
- **Webhook Handling**: Process incoming WhatsApp messages and send responses
- **Business Account Management**: Link multiple WhatsApp Business accounts
- **Message Threading**: Support for conversation continuity
- **Embedded Signup**: Complete WhatsApp Business API setup flow
- **Test Messaging**: Built-in test message functionality

#### 4. **CRM Functionality**
- **Customer Profiles**: Store customer information (name, email, phone, bot interactions)
- **Lead Tracking**: Automatic CRM entry creation from conversations
- **Data Enrichment**: Update customer profiles from chat interactions
- **Conversation History**: Full customer interaction timeline
- **Multi-channel Customer**: Link customers across web and WhatsApp

#### 5. **Push Notifications**
- **Anonymous Subscriptions**: Support for anonymous push notifications
- **User Notifications**: Alert admins when human handoff is requested
- **Multi-device Support**: Web push notifications across devices
- **Notification Templates**: Structured notification content

#### 6. **Demo Bot System**
- **Demo Bot Management**: Create temporary bots for website demonstrations
- **URL-based Bots**: Automatic bot creation and KB population from URLs
- **Status Tracking**: Monitor demo bot creation and scraping progress
- **Trial Experience**: Complete demo flow for potential customers

#### 7. **Payment & Subscription Management**
- **Subscription Plans**: STARTER and PRO plan management
- **Payment Integration**: PayStack payment verification
- **Billing Cycles**: Monthly subscription tracking
- **Payment History**: Complete transaction records
- **Plan Upgrades**: Seamless plan transition handling

### Database Schema (Supabase)
```sql
-- Core conversation management
conversations {
  id: uuid (primary key)
  bot_id: uuid (foreign key)
  customer_email: text
  customer_name: text
  customer_phone: text
  channel: text (web/whatsapp)
  status: text (ai/human/closed/awaiting_name)
  handoff_requests: integer
  read: boolean
  created_at: timestamp
  updated_at: timestamp
}

messages {
  id: uuid (primary key)
  conversation_id: uuid (foreign key)
  content: text
  role: text (user/bot/human)
  read: boolean
  reply_to_message_id: uuid
  created_at: timestamp
}

-- Bot and integration management
bots {
  id: uuid (primary key)
  kb_id: text (foreign key to knowledge_bases)
  name: text
  company: text
  user_id: uuid
  created_at: timestamp
}

whatsapp_configs {
  id: uuid (primary key)
  bot_id: uuid (foreign key)
  access_token: text (encrypted)
  phone_number_id: text
  waba_id: text
  business_id: text
  webhook_verify_token: text
  is_active: boolean
}

-- CRM and customer management
bot_crms {
  id: uuid (primary key)
  bot_id: uuid (foreign key)
  first_name: text
  last_name: text
  phone_number: text
  email: text
  created_at: timestamp
  updated_at: timestamp
}

-- User management and authentication
users {
  id: uuid (primary key)
  email: text
  created_at: timestamp
  updated_at: timestamp
}

-- Payment and subscription management
subscriptions {
  id: uuid (primary key)
  user_id: uuid (foreign key)
  plan_name: text (STARTER/PRO)
  price: decimal
  billing_cycle: text
  status: text (active/cancelled/expired)
  start_date: timestamp
  end_date: timestamp
  payment_reference: text
  created_at: timestamp
  updated_at: timestamp
}

-- Push notifications
anon_push_subscriptions {
  id: uuid (primary key)
  user_id: uuid
  anon_id: text
  subscription: jsonb
  created_at: timestamp
}

-- Demo bot system
demo_bots {
  id: uuid (primary key)
  url: text
  kb_id: text
  status: text (processing/completed/failed)
  created_at: timestamp
}

-- Human handoff tracking
handover_requests {
  id: uuid (primary key)
  conversation_id: uuid (foreign key)
  last_message_id: uuid
  created_at: timestamp
}

-- NEW: Vector storage for knowledge bases
knowledge_bases {
  kb_id: text (primary key)
  name: text
  agent_name: text
  created_at: timestamptz
}

knowledge_base_documents {
  id: uuid (primary key)
  kb_id: text (foreign key)
  document_id: text
  content: text  -- original chunk
  ctx_text: text  -- contextualized chunk
  embedding: vector(1024)  -- Cohere embeddings
  metadata: jsonb
  created_at: timestamptz
}

-- Hybrid search function
hybrid_search(kb_id, query_text, query_embedding, match_count)
  -> Returns documents ranked by combined vector + BM25 score
```

## WhatsApp Business API Integration

### Complete WhatsApp Integration Flow

#### 1. **Embedded Signup Process**
- **Authorization Code Exchange**: Convert authorization codes to access tokens
- **Business Account Linking**: Associate WhatsApp Business accounts with bots
- **Phone Number Registration**: Link phone numbers to specific bots
- **Webhook Configuration**: Automatic webhook setup and verification

#### 2. **Message Processing Pipeline**
```
WhatsApp Message → Webhook Verification → Bot Identification → Conversation Lookup → AI Processing → Response Sending
     ↓                    ↓                     ↓                    ↓               ↓              ↓
Meta Webhook → Token Validation → Phone Number Mapping → Supabase Query → LangChain Agent → WhatsApp API
```

#### 3. **Customer Onboarding Flow**
- **First-time Users**: Automatic name collection workflow
- **Conversation Creation**: Dynamic conversation initialization
- **CRM Integration**: Automatic customer profile creation
- **Welcome Messages**: Contextual greeting and instruction

#### 4. **WhatsApp Features**
- **Two-way Messaging**: Send and receive text messages
- **Conversation Continuity**: Persistent conversation threading
- **Human Handoff**: Seamless transition to human agents
- **Status Tracking**: Message delivery and read receipts
- **Test Messaging**: Built-in testing functionality

### WhatsApp API Endpoints
- `POST /whatsapp/setup/{bot_id}` - Complete embedded signup
- `GET /whatsapp/config/{bot_id}` - Get configuration
- `PUT /whatsapp/config/{kb_id}/toggle` - Toggle active status
- `DELETE /whatsapp/config/{kb_id}` - Remove integration
- `POST /whatsapp/webhook` - Message webhook handler
- `GET /whatsapp/webhook` - Webhook verification
- `POST /whatsapp/test-message/{bot_id}` - Send test messages
- `GET /whatsapp/configs` - List all integrations (admin)
- `POST /whatsapp/whatsapp-from-agent` - Send messages from agents

## Payment System (PayStack Integration)

### Payment Processing Flow

#### 1. **Subscription Plans**
- **STARTER Plan**: NGN 300.50 (30,050 kobo)
- **PRO Plan**: NGN 403.33 (40,333 kobo)
- **Automatic Plan Detection**: Based on payment amount
- **Monthly Billing**: 30-day subscription cycles

#### 2. **Payment Verification Process**
```
PayStack Payment → Reference Generation → Backend Verification → Subscription Activation → User Notification
       ↓                   ↓                      ↓                     ↓                    ↓
Frontend Payment → Unique Reference → API Call → Database Update → Email Confirmation
```

#### 3. **Payment Endpoints**
- `GET /payments/check-subscription` - Verify payment and activate subscription
- **Parameters**: `reference` (PayStack reference), `user_id` (user UUID)
- **Response**: Payment verification status and subscription details

#### 4. **Database Updates**
When payment is verified:
- **users_metadata**: Update payment_status to "PRO" or "STARTER"
- **subscriptions**: Create new subscription record
- **Automatic Calculations**: Set start_date and end_date (30 days)
- **Reference Tracking**: Store PayStack reference for records

### PayStack Integration Models
```python
PayStackResponse: Complete payment response structure
PayStackData: Payment transaction details
PayStackCustomer: Customer information
PayStackAuthorization: Payment method details
CheckSubscriptionResponse: Verification response format
```

## Email Notification System (AWS SES)

### Email Service Architecture

#### 1. **AWS SES Integration**
- **Template System**: Pre-defined HTML email templates
- **Multi-recipient**: Support for multiple email addresses
- **Delivery Tracking**: Email delivery confirmation
- **Error Handling**: Graceful failure management

#### 2. **Email Templates**
- **DeskforceUserMessageWithLink**: Admin notifications for new user messages
- **DeskforceClientMessageWithLink**: Client notifications for human responses
- **Dynamic Content**: Personalized email content with variables

#### 3. **Notification Triggers**
- **New User Messages**: Notify admins when users send messages
- **Human Responses**: Notify customers when agents respond
- **Offline Notifications**: Email when bots are offline
- **Handoff Requests**: Immediate notifications for human assistance

#### 4. **Email Functions**
```python
notify_admin_on_user_message(): Send admin notifications
notify_client_message(): Send client notifications  
create_ses_template(): Create email templates
```

### Email Configuration
```bash
SES_ACCESS_KEY=aws_access_key
SES_SECRET_ACCESS_KEY=aws_secret_key
SES_REGION=aws_region
SENDER_EMAIL=hello@deskforce.co.za
VITE_BASE_URL=frontend_base_url
```

## API Architecture

### REST Endpoints

#### Agent Management (`/agents`)
- `POST /agents` - Create new agent/KB
- `DELETE /agents/{kb_id}` - Delete agent and all data
- `GET /agents` - List all agents with summaries
- `POST /agents/{kb_id}/json` - Populate KB from JSON
- `GET /agents/{kb_id}/content` - Retrieve KB content
- `POST /agents/{kb_id}/cleanup` - Remove duplicates
- `GET /agents/{kb_id}/config` - Get agent configuration
- `PUT /agents/{kb_id}/config` - Update agent settings

#### Chat System (`/chat`)
- `POST /agents/{kb_id}/chat` - HTTP chat with agent
- `POST /agents/{kb_id}/human_response` - Human takeover response
- `GET /agents/{kb_id}/history` - Get conversation history
- `DELETE /agents/{kb_id}/history` - Clear conversation history
- `POST /agents/{kb_id}/human-chat` - Human agent response
- `POST /agents/{kb_id}/human-knowledge` - Add verified knowledge
- `GET /conversations` - List conversations with handoff status

#### File Management (`/files`)
- `POST /agents/{kb_id}/upload` - Upload and process files
- `GET /agents/{kb_id}/files` - List uploaded files

#### Web Scraping (`/scrape`)
- `POST /agents/{kb_id}/scrape-url` - Initiate background scraping
- `GET /agents/{kb_id}/scrape-status` - Check scraping progress

#### Bot Management (`/bots`)
- `POST /bots/{bot_id}/knowledge` - Add human-verified knowledge
- `POST /bots/{bot_id}/scrape-url` - Initiate bot-specific scraping
- `POST /bots/{bot_id}/chat` - Chat with specific bot
- `POST /bots/{bot_id}/conversations` - Create new conversation
- `GET /bots/{bot_id}/conversations` - List bot conversations
- `POST /bots/{bot_id}/chat_human` - Human chat response
- `POST /bots/demo-bot` - Create demo bot for URL
- `POST /send-msg-demobot` - Send message to demo bot

#### WhatsApp Integration (`/whatsapp`)
- `POST /whatsapp/setup/{bot_id}` - Complete WhatsApp Business setup
- `GET /whatsapp/config/{bot_id}` - Get WhatsApp configuration
- `PUT /whatsapp/config/{kb_id}/toggle` - Toggle integration active/inactive
- `DELETE /whatsapp/config/{kb_id}` - Remove WhatsApp integration
- `POST /whatsapp/webhook` - Handle incoming WhatsApp messages
- `GET /whatsapp/webhook` - Webhook verification endpoint
- `POST /whatsapp/test-message/{bot_id}` - Send test messages
- `GET /whatsapp/configs` - List all WhatsApp integrations (admin)
- `POST /whatsapp/whatsapp-from-agent` - Send agent messages via WhatsApp

#### Payment System (`/payments`)
- `GET /payments/check-subscription` - Verify PayStack payment and activate subscription

#### Online Status Management (`/status`)
- `POST /status` - Set bot online status
- `GET /status/{bot_id}` - Get bot online status
- `POST /status/user` - Set user online status
- `GET /status/user/{user_email}/{bot_id}` - Get user online status

#### Push Notifications (`/notifications`)
- `POST /notifications/save-subscription` - Save push notification subscription

#### WebSocket Endpoints
- `WS /ws/{conversation_id}` - Real-time chat for users
- `WS /ws/agent/{conversation_id}` - Real-time chat for agents

### Background Tasks
- **Web Scraping**: Asynchronous scraping with status tracking
- **File Processing**: Large file handling without blocking requests
- **Status Updates**: Real-time progress reporting
- **Email Notifications**: Asynchronous email sending

## Agent System Deep Dive

### LLM Integration
The system supports multiple LLM providers with automatic fallback:

1. **Google Gemini** (Primary)
   - Model: `gemini-1.5-flash`
   - Fast and cost-effective
   - Good for conversational AI

2. **DeepSeek** (Fallback)
   - Model: `deepseek-chat`
   - Uses OpenAI-compatible API
   - Alternative provider

3. **OpenAI** (Optional)
   - Various models supported
   - Premium option

### Conversation Flow
```
User Message → Conversation Setup → Memory Loading → Agent Creation → Tool Usage → Response Generation → Multi-DB Storage
     ↓               ↓                   ↓              ↓            ↓              ↓                     ↓
Multi-Channel → Supabase Conversation → SQLite Config → LangChain → KB Retrieval → LLM Processing → Supabase + SQLite
(Web/WhatsApp)      Management           Loading         Agent      (ChromaDB)      (Gemini/DeepSeek)    Storage
```

### Tool System
- **Knowledge Base Retriever**: Semantic search in vector database
- **Answer Generator**: LLM-powered response generation
- **Knowledge Updater**: Add new information to KB (optional)

### Human Handoff System
- **Trigger Conditions**: No relevant information, complex queries, user requests
- **Handoff Marker**: `(needs help)` appended to responses
- **Human Interface**: Separate endpoints for human agents
- **Context Preservation**: Full conversation history available
- **Email Notifications**: Automatic admin notifications
- **Status Management**: Conversation status updates

## File Processing Pipeline

### Ingestion Flow
```
File Upload → Metadata Storage → Content Extraction → Text Processing → Context Generation → Embedding → Supabase Storage
     ↓             ↓                    ↓                ↓                    ↓             ↓            ↓
  FastAPI → SQLite Record → File Parser → Text Chunking → Anthropic Claude → Cohere → Supabase Vector
```

### Query Flow
```
User Query → Embed Query → Hybrid Search → Optional Reranking → Context Assembly → LLM Response
     ↓            ↓              ↓                ↓                   ↓               ↓
 FastAPI → Cohere Embed → Supabase RPC → Cohere Rerank → Document Retrieval → Gemini/DeepSeek
```

### Processing Features
- **Format Detection**: Automatic file type identification
- **Error Handling**: Graceful failure with user feedback
- **Progress Tracking**: File processing status
- **Metadata Preservation**: Original file information retained
- **Multi-file Support**: Batch file processing

## Web Scraping System

### Scraping Architecture
- **Browser Engine**: Playwright with Chromium
- **Parallel Processing**: Multiple pages scraped concurrently
- **Content Focus**: Smart selection of main content areas
- **Resource Blocking**: Faster scraping by blocking images/scripts

### Business Intelligence Extraction
The scraper uses LLM analysis to extract:
- Company information and descriptions
- Products and services offered
- Pricing information and payment options
- Contact details and social media
- Value propositions and target audience
- FAQs and support information

### Configuration Options
```json
{
  "MAX_INTERNAL_PAGES": 15,
  "MAX_CONCURRENT_SCRAPES": 5,
  "PAGE_LOAD_TIMEOUT": 20000,
  "CONTENT_WAIT_TIMEOUT": 2000,
  "BLOCK_RESOURCES": true,
  "TARGET_CONTENT_SELECTORS": ["main", "article", ".content"],
  "PRIORITY_URL_PATTERNS": ["/about", "/contact", "/pricing"]
}
```

## Configuration Management

### Environment Variables
```bash
# LLM Configuration
GOOGLE_API_KEY=your_gemini_api_key
DEEPSEEK_API_KEY=your_deepseek_key
DEEPSEEK_API_BASE=https://api.deepseek.com/v1
OPENAI_API_KEY=your_openai_key
ANTHROPIC_API_KEY=your_anthropic_key  # NEW: For context generation
COHERE_API_KEY=your_cohere_key  # NEW: For embeddings + reranking

# Storage Paths
# CHROMADB_PATH=./chromadb_data  # DEPRECATED - Being removed
SQLITE_DB_DIR=./db
SQLITE_DB_FILENAME=kb_metadata.sqlite

# Supabase Configuration (Primary Database)
SUPABASE_URL=your_supabase_url
SUPABASE_SERVICE_ROLE_KEY=your_service_role_key

# WhatsApp Business API Integration
WHATSAPP_ACCESS_TOKEN=your_whatsapp_token
WHATSAPP_PHONE_NUMBER_ID=your_phone_number_id
FACEBOOK_APP_ID=your_facebook_app_id
FACEBOOK_APP_SECRET=your_facebook_app_secret

# PayStack Payment Integration
PAYSTACK_SECRET_KEY=your_paystack_secret_key
PAYSTACK_PUBLIC_KEY=your_paystack_public_key

# AWS SES Email Configuration
SES_ACCESS_KEY=your_aws_access_key
SES_SECRET_ACCESS_KEY=your_aws_secret_key
SES_REGION=your_aws_region
SENDER_EMAIL=your_sender_email

# Redis Configuration
REDIS_URL=your_redis_url
REDIS_HOST=your_redis_host
REDIS_PORT=your_redis_port
REDIS_PASSWORD=your_redis_password

# Application Settings
BASE_URL=https://yourdomain.com
VITE_BASE_URL=https://your-frontend-url.com
CORS_ORIGINS=https://example.com,https://app.example.com
EXPIRY_STATUS_TIME=300  # Redis status expiry in seconds
```

### Per-Agent Configuration
Each agent can be individually configured:
- **System Prompt**: Customizable AI personality and instructions
- **Max Iterations**: Limit for agent reasoning loops
- **Response Style**: Tone, formatting, and behavior settings

## CRM Integration

### Customer Management System

#### 1. **Automatic Customer Profiles**
- **Profile Creation**: Automatic customer entry creation from conversations
- **Data Enrichment**: Update profiles from chat interactions
- **Multi-channel Linking**: Connect customers across web and WhatsApp
- **Contact Information**: Store names, emails, phone numbers

#### 2. **Lead Tracking**
- **Conversation History**: Full customer interaction timeline
- **Engagement Metrics**: Track customer engagement levels
- **Bot Interactions**: Record interactions with specific bots
- **Follow-up Management**: Track conversation status and handoffs

#### 3. **CRM Data Structure**
```python
bot_crms {
  id: uuid
  bot_id: uuid  # Links to specific bot
  first_name: text
  last_name: text
  phone_number: text
  email: text
  created_at: timestamp
  updated_at: timestamp
}
```

#### 4. **CRM Functions**
```python
ensure_crm_entry(): Create or update customer profiles
get_customer_history(): Retrieve full customer interaction history
update_customer_data(): Enrich customer profiles from conversations
```

## Development Workflow

### Startup Process
1. **Environment Loading**: Load `.env` configuration
2. **Database Initialization**: Create SQLite tables if needed
3. ~~**ChromaDB Setup**: Initialize vector database client~~ **Supabase Vector Setup**: Initialize pgvector connection
4. **Supabase Connection**: Establish PostgreSQL connection
5. **Redis Connection**: Initialize status tracking client
6. **LLM Initialization**: Configure and test AI models (including Anthropic + Cohere)
7. **FastAPI Launch**: Start web server with all routes
8. **WebSocket Server**: Initialize real-time chat server

### Key Development Files
```
main.py                 # FastAPI application and main endpoints
app/
├── api/
│   └── routes/         # All API route modules
│       ├── agent.py    # Agent management endpoints
│       ├── chat.py     # Chat and WebSocket endpoints
│       ├── whatsapp.py # WhatsApp Business API integration
│       ├── payment.py  # PayStack payment processing
│       ├── bot.py      # Bot management endpoints
│       ├── file.py     # File upload and processing
│       ├── scrape.py   # Web scraping endpoints
│       └── online_status.py # Redis status management
├── core/               # Core business logic
│   ├── kb_manager.py   # ChromaDB vector database management (BEING REPLACED)
│   ├── supabase_kb_manager.py # NEW: Supabase vector database management
│   ├── embeddings.py   # NEW: Cohere embeddings wrapper
│   ├── contextualizer.py # NEW: Anthropic context generation
│   ├── db_manager.py   # SQLite metadata database operations
│   ├── agent_manager.py # LangChain agent creation and management
│   ├── file_parser.py  # Multi-format file content extraction
│   ├── scraper.py      # Intelligent web scraping with Playwright
│   ├── tools.py        # LangChain tools for agent capabilities
│   ├── config.py       # Configuration and LLM initialization
│   └── data_processor.py # Text processing and chunking utilities
├── models/             # Pydantic data models
│   ├── agent.py        # Agent-related models
│   ├── chat.py         # Chat and conversation models
│   ├── whatsapp.py     # WhatsApp integration models
│   ├── payment.py      # PayStack payment models
│   ├── bot.py          # Bot management models
│   └── file.py         # File upload models
├── services/           # External service integrations
│   ├── send_email.py   # AWS SES email service
│   ├── push_notifications.py # Push notification service
│   └── agent_service.py # Agent business logic
├── utils/              # Utility functions
│   ├── text_processing.py # Text cleaning and processing
│   ├── verification.py # User authentication utilities
│   └── crm_utils.py    # CRM helper functions
└── config/             # Configuration management
    ├── settings.py     # Application settings
    ├── redisconnection.py # Redis connection management
    └── supabase_client.py # Supabase client configuration
```

### Testing Strategy
- **Unit Tests**: Individual component testing
- **Integration Tests**: End-to-end workflow testing
- **API Tests**: FastAPI endpoint validation
- **Component Tests**: Core functionality verification
- **WebSocket Tests**: Real-time communication testing
- **Payment Tests**: PayStack integration testing
- **Vector Search Tests**: Hybrid search accuracy validation
- **Context Generation Tests**: RAG enhancement verification

## Deployment Considerations

### Production Setup
- **Environment Variables**: Secure API key management
- **Database Persistence**: Persistent volume mounting for data
- **Resource Management**: Memory and CPU allocation for embeddings
- **Monitoring**: Logging and error tracking
- **Scaling**: Horizontal scaling considerations for multiple instances
- **Redis Cluster**: High-availability status tracking
- **Load Balancing**: WebSocket connection distribution

### Performance Optimization
- **Context Caching**: LRU cache for 90% cost reduction
- **Batch Embeddings**: Process up to 96 texts per Cohere API call
- **Connection Pooling**: Efficient database connections
- **Background Processing**: Non-blocking file and scraping operations
- **Memory Management**: Proper cleanup of large objects
- **Redis Optimization**: Efficient status data structures
- **WebSocket Optimization**: Connection pooling and message batching
- **Hybrid Search**: Optimized IVFFlat indexes for fast vector search

### Security Features
- **API Key Protection**: Secure storage and rotation
- **Input Validation**: Comprehensive request validation
- **Error Handling**: No sensitive information leakage
- **CORS Configuration**: Proper cross-origin request handling
- **JWT Verification**: Secure user authentication
- **Webhook Verification**: WhatsApp webhook signature validation
- **Payment Security**: Secure PayStack integration

## Future Enhancements

### Implemented Features ✅
- **Multi-channel Support**: Web widget and WhatsApp Business API
- **Real-time Chat**: Live message synchronization via WebSocket
- **User Authentication**: JWT-based auth system
- **CRM Integration**: Automatic customer profile management
- **Push Notifications**: Anonymous and user-based notifications
- **Multi-user Support**: Bot sharing and team collaboration
- **Payment System**: PayStack integration with subscription management
- **Email Notifications**: AWS SES integration for automated notifications
- **Online Status Tracking**: Redis-based presence management
- **Human Handoff**: Complete workflow with email notifications

### Planned Features
- **Multi-modal Support**: Image and video content processing
- **Advanced Analytics**: Usage tracking and performance metrics
- **Custom Integrations**: Additional webhook and API integrations
- **Advanced Scraping**: JavaScript-heavy site support
- **Enterprise Features**: SSO, advanced permissions, audit logs
- **Custom Models**: Support for local and custom LLMs
- **Voice Integration**: Voice chat capabilities
- **Mobile Apps**: Native mobile applications
- **Advanced CRM**: Enhanced customer management features

### Scalability Roadmap
- **Microservices**: Split components into separate services
- **Queue System**: Redis/RabbitMQ for background tasks
- **Load Balancing**: Multiple instance support with WebSocket clustering
- **Cloud Storage**: S3/GCS for file and data storage
- **Database Scaling**: PostgreSQL horizontal scaling
- **CDN Integration**: Global content delivery
- **Auto-scaling**: Dynamic resource allocation
- **Monitoring**: Advanced APM and alerting systems

This backend provides a robust foundation for AI-powered sales agents with comprehensive knowledge management using state-of-the-art Contextual RAG, intelligent content processing, real-time communication, multi-channel support, payment processing, and seamless human handoff capabilities.