from mcp.server.mcpserver import MCPServer

from app.services.postajob import JobPoster, PublishRequest


def build_job_server(poster: JobPoster) -> MCPServer:
    """Expose the Telegram job post as one MCP tool."""
    server: MCPServer = MCPServer("sift-jobs")

    @server.tool(description="Post one approved job to the Telegram channel.")
    async def post_job(
        title: str,
        description: str,
        apply_url: str,
        contract: str,
        category: str,
        company_name: str,
        company_country: str,
        seniority: str,
        skills: list[str],
        version_id: str,
        apply_email: str = "",
        mail_subject: str = "",
    ) -> str:
        result = await poster.publish(
            PublishRequest(
                title=title,
                description=description,
                apply_url=apply_url,
                contract=contract,
                category=category,
                company_name=company_name,
                company_country=company_country,
                seniority=seniority,
                skills=skills,
                version_id=version_id,
                apply_email=apply_email,
                mail_subject=mail_subject,
            )
        )
        return result.model_dump_json()

    return server
