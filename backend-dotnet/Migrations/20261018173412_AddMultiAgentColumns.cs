using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace FinAgent.Api.Migrations
{
    /// <inheritdoc />
    public partial class AddMultiAgentColumns : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.AddColumn<string>(
                name: "SentimentReport",
                table: "AnalysisJobs",
                type: "nvarchar(max)",
                nullable: true);

            migrationBuilder.AddColumn<string>(
                name: "SynthesisReport",
                table: "AnalysisJobs",
                type: "nvarchar(max)",
                nullable: true);
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropColumn(
                name: "SentimentReport",
                table: "AnalysisJobs");

            migrationBuilder.DropColumn(
                name: "SynthesisReport",
                table: "AnalysisJobs");
        }
    }
}
