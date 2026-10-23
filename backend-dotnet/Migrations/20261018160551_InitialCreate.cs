using System;
using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace FinAgent.Api.Migrations
{
    /// <inheritdoc />
    public partial class InitialCreate : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.CreateTable(
                name: "PortfolioItems",
                columns: table => new
                {
                    Id = table.Column<int>(type: "int", nullable: false)
                        .Annotation("SqlServer:Identity", "1, 1"),
                    TickerSymbol = table.Column<string>(type: "nvarchar(max)", nullable: false),
                    Quantity = table.Column<decimal>(type: "decimal(18,4)", nullable: false),
                    AverageCost = table.Column<decimal>(type: "decimal(18,4)", nullable: false),
                    CreatedAt = table.Column<DateTime>(type: "datetime2", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_PortfolioItems", x => x.Id);
                });

            migrationBuilder.CreateTable(
                name: "AnalysisJobs",
                columns: table => new
                {
                    Id = table.Column<Guid>(type: "uniqueidentifier", nullable: false),
                    PortfolioItemId = table.Column<int>(type: "int", nullable: false),
                    TickerSymbol = table.Column<string>(type: "nvarchar(max)", nullable: false),
                    Status = table.Column<string>(type: "nvarchar(max)", nullable: false),
                    FundamentalReport = table.Column<string>(type: "nvarchar(max)", nullable: true),
                    SourcesJson = table.Column<string>(type: "nvarchar(max)", nullable: true),
                    Disclaimer = table.Column<string>(type: "nvarchar(max)", nullable: false),
                    ErrorMessage = table.Column<string>(type: "nvarchar(max)", nullable: true),
                    CreatedAt = table.Column<DateTime>(type: "datetime2", nullable: false),
                    CompletedAt = table.Column<DateTime>(type: "datetime2", nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_AnalysisJobs", x => x.Id);
                    table.ForeignKey(
                        name: "FK_AnalysisJobs_PortfolioItems_PortfolioItemId",
                        column: x => x.PortfolioItemId,
                        principalTable: "PortfolioItems",
                        principalColumn: "Id",
                        onDelete: ReferentialAction.Cascade);
                });

            migrationBuilder.CreateIndex(
                name: "IX_AnalysisJobs_PortfolioItemId",
                table: "AnalysisJobs",
                column: "PortfolioItemId");
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropTable(
                name: "AnalysisJobs");

            migrationBuilder.DropTable(
                name: "PortfolioItems");
        }
    }
}
