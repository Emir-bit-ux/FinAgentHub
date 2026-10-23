using FinAgent.Api.Entities;
using Microsoft.EntityFrameworkCore;

namespace FinAgent.Api.Data
{
    public class AppDbContext : DbContext
    {
        public AppDbContext(DbContextOptions<AppDbContext> options) : base(options) { }

        public DbSet<PortfolioItem> PortfolioItems { get; set; }
        public DbSet<AnalysisJob> AnalysisJobs { get; set; }

        protected override void OnModelCreating(ModelBuilder modelBuilder)
        {
            base.OnModelCreating(modelBuilder);

            modelBuilder.Entity<PortfolioItem>().Property(p => p.Quantity).HasColumnType("decimal(18,4)");
            modelBuilder.Entity<PortfolioItem>().Property(p => p.AverageCost).HasColumnType("decimal(18,4)");
            modelBuilder.Entity<PortfolioItem>().Property(p => p.AverageFxRate).HasColumnType("decimal(18,4)");
            modelBuilder.Entity<PortfolioItem>().Property(p => p.RealizedPnlTry).HasColumnType("decimal(18,4)");
        }
    }
}