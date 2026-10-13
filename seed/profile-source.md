# Akin Gungor — Software Engineer

Wilton, NH. akingungor@yahoo.com. linkedin.com/in/akin-gungor.
akin-gungor.vercel.app. github.com/akngngr.

## Overview

Software engineer with 5+ years building, integrating, and deploying custom
software directly inside client environments for a 7M-user enterprise SaaS
platform. Works across Python, C#/.NET, JavaScript/TypeScript and React, with
REST APIs and SQL. Owns the technical relationship inside enterprise client
environments, including Fortune 500 pharmaceutical accounts, debugging live
production issues and shipping fixes directly.

Recent focus is applying generative AI to real operational work: a production
retrieval-augmented generation (RAG) knowledge system, Azure OpenAI rollout
into live client environments, and automated agent workflows for routing and
summarisation. Builds the reusable frameworks teams depend on, including a
versioned diagnostic query library adopted across Support and Engineering.

## Current role — AKUMINA, Senior Technical Support Engineer (April 2022 to July 2026)

Embedded engineering lead acting as the technical bridge between product
engineering and strategic enterprise clients on a 7M-user SaaS platform.
Functionally owned client-facing software delivery end to end, from initial
scoping through production architecture and code deployment.

Built and shipped a production RAG knowledge retrieval system on Azure OpenAI
(vector database, embedding pipelines, Azure AI Search) that indexed
unstructured context automatically, cutting search time by 50% and resolution
time by 25%. Designed 5 autonomous agent workflows handling automated routing
and summarisation.

Owned the forward-deployed rollout of Azure OpenAI (GPT-4.5, DALL-E) features
into live client environments. Validated end-to-end API connectivity, debugged
live integration issues, resolved Azure Front Door firewall and WAF problems
affecting client access, and enabled client teams on new AI tooling.

Built a versioned KQL diagnostic query library adopted across Support and
Engineering, reducing root-cause triage time by 50%. Acted as subject-matter
expert for enterprise search across Microsoft 365 components, resolving search
escalations through debugging, code-level fixes and configuration changes.

Shipped custom React components and automated CI/CD deployment pipelines for
bespoke client extensions, incorporating automated testing into the deployment
pipeline and reducing upgrade cycle durations by 60%.

Served as primary technical delivery lead for a Fortune 500 enterprise client,
leading architectural touchpoints to align product roadmaps, build custom
client features, and maintain platform reliability. Acted as subject-matter
expert for client developer teams, unblocking their project work and advising
on third-party API integrations.

Used PowerShell and scripting for install, configuration and upgrade tasks,
automating manual steps to reduce repetitive hands-on work. Supported a mobile
app rollout on iOS devices, troubleshooting MDM configuration and monitoring
endpoint health in Azure.

Facilitated onboarding and document/data migrations for enterprise accounts.
Created and maintained knowledge base articles, runbooks and troubleshooting
playbooks. Built proof-of-concept environments for prospects during pre-sales
and walked customer teams through product demos tailored to the features they
were evaluating.

## Independent Technical Consultant (2018 to present)

Delivered custom React and TypeScript integrations and REST/SOAP based API
solutions for clients with specialized data workflows, including
pharmaceutical and enterprise IT clients, through full dev-to-prod cycles.

Supported critical IT infrastructure for LSNE/PCI Pharma during a large-scale
Active Directory migration, maintaining operational uptime, resolving complex
technical escalations, and troubleshooting TCP/IP connectivity during the
domain migration.

Leveraged agentic coding tools to prototype product architectures, evaluate
system tradeoffs and build bespoke technical tools at high velocity.

## Projects

Enterprise Knowledge and Support Copilot. A production dual-engine RAG copilot
deployed on Render and Supabase. Gemini is the default generation path and an
environment flag switches to local Ollama when available, with automatic
fallback to Gemini when the local path is slow or unreachable, so the service
keeps answering through an outage. Vector storage in PostgreSQL with pgvector
using cosine similarity over 768-dimension embeddings. Every answer returns its
source chunks, so responses are verifiable rather than opaque.

Voxal Analytics Dashboard. A voice- and text-driven analytics dashboard where
a question asked out loud or typed is parsed into a live chart. Supports CSV
upload for arbitrary datasets with dynamic schema inference and query-to-chart
mapping built from scratch.

Printmeasure 3D Model Inspector. A React tool that computes volume, length and
material estimates from OBJ and STL files for pre-print inspection, replicating
core slicer functionality including shape recognition and filament analysis.

## Technical skills

Languages: Python, C# (.NET), JavaScript, TypeScript, SQL, KQL, Lua,
PostgreSQL, PowerShell, Bash.

Frontend: React, Next.js, HTML, CSS, Material UI, responsive mobile-first design,
accessibility (WCAG).

Cloud and platform: Azure Cloud Infrastructure, Azure Front Door with reverse
proxy and WAF, Azure DevOps CI/CD, automated testing within the deployment
pipeline, Docker containerization, Kubernetes fundamentals, Linux, Windows.

AI and data: Azure OpenAI (GPT-4.5, DALL-E), Azure AI Search, RAG pipelines,
vector embeddings, pgvector, dual-engine model orchestration with fallback.

APIs and integration: REST APIs, GraphQL, webhooks, Microsoft Graph API, Okta
SSO/OAuth, Active Directory domain migrations, XML/SOAP, TCP/IP.

Practices: SOC 2 and GDPR security and data privacy frameworks, identity and
access management, knowledge base articles, runbooks, troubleshooting playbooks.

## Earlier role

Operations Manager, UBREAKIFIX (2020 to 2021). Managed daily service
operations and implemented Jira ticketing workflows to track recurring
incidents and prioritise repair tasks, increasing technical service revenue by
48%.

## Education and certifications

Bachelor of Science, Chemical and Process Engineering, Yalova University.

Associate of Science, Information and Technology, Monroe Community College.

Foundational C# Certification, FreeCodeCamp and Microsoft, 2026.
Front-end Development Libraries Certification, FreeCodeCamp, 2026.