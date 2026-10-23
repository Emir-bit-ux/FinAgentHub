using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace FinAgent.Api.Migrations
{
    /// <inheritdoc />
    public partial class AddFxAndRealizedPnl : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.AddColumn<decimal>(
                name: "AverageFxRate",
                table: "PortfolioItems",
                type: "decimal(18,4)",
                nullable: false,
                defaultValue: 0m);

            migrationBuilder.AddColumn<decimal>(
                name: "RealizedPnlTry",
                table: "PortfolioItems",
                type: "decimal(18,4)",
                nullable: false,
                defaultValue: 0m);
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropColumn(
                name: "AverageFxRate",
                table: "PortfolioItems");

            migrationBuilder.DropColumn(
                name: "RealizedPnlTry",
                table: "PortfolioItems");
        }
    }
}
