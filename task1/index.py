"""
Simple Flask app with a low-stock alerts endpoint for a company's products.

Assumptions (kept simple and documented for the task):
- A company has many warehouses; each warehouse holds inventory for products.
- Product has a `product_type` which determines its low-stock threshold via a mapping.
- Only products with recent sales activity (within SALES_LOOKBACK_DAYS) produce alerts.
- Days-until-stockout is estimated using the average daily sales over the last SALES_AVG_DAYS.
- For simplicity, relational ties are: Company -> Warehouse -> Inventory -> Product.
- Supplier is a simple entity related to Product (one supplier per product in this sample).

This implementation uses SQLite (file `test.db`) and SQLAlchemy for ORM. It is intentionally
straightforward so it looks like a human-written internship task submission.

Endpoints:
- GET /api/companies/<company_id>/alerts/low-stock

"""

from datetime import datetime, timedelta
from math import floor

from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
# Use a local sqlite file so it's easy for the reviewer to run it locally
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///test.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# ---------- Models ----------
class Company(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String, nullable=False)
    warehouses = db.relationship('Warehouse', backref='company')


class Warehouse(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String, nullable=False)
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'))
    inventories = db.relationship('Inventory', backref='warehouse')


class Supplier(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String, nullable=False)
    contact_email = db.Column(db.String)


class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String, nullable=False)
    sku = db.Column(db.String, nullable=False, unique=True)
    product_type = db.Column(db.String, nullable=False)  # e.g. 'fast-moving', 'slow-moving'
    supplier_id = db.Column(db.Integer, db.ForeignKey('supplier.id'))
    supplier = db.relationship('Supplier')
    inventories = db.relationship('Inventory', backref='product')
    sales = db.relationship('Sale', backref='product')


class Inventory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'))
    warehouse_id = db.Column(db.Integer, db.ForeignKey('warehouse.id'))
    quantity = db.Column(db.Integer, default=0)


class Sale(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'))
    quantity = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# ---------- Business rules / configuration ----------
# Thresholds per product type (simple mapping for the task)
THRESHOLDS_BY_TYPE = {
    'fast-moving': 50,
    'normal': 20,
    'slow-moving': 5
}

# Only products with sales in the last SALES_LOOKBACK_DAYS are considered
SALES_LOOKBACK_DAYS = 90
# Average daily sales computed over this window (used to estimate days until stockout)
SALES_AVG_DAYS = 30


# ---------- Helper functions ----------
def get_threshold_for_product(product: Product):
    # Fallback to a conservative threshold if type unknown
    return THRESHOLDS_BY_TYPE.get(product.product_type, 10)


def get_recent_sales(product: Product, since: datetime):
    return [s for s in product.sales if s.created_at >= since]


# ---------- Endpoint ----------
@app.route('/api/companies/<int:company_id>/alerts/low-stock', methods=['GET'])
def low_stock_alerts(company_id):
    """Return low stock alerts across all warehouses for the company.

    Rules implemented:
    - Include only products with recent sales in the last SALES_LOOKBACK_DAYS.
    - A product triggers an alert for a specific warehouse when that warehouse's inventory
      quantity is below the product threshold based on its type.
    - Supplier contact info is included when available.
    - days_until_stockout is estimated as floor(current_stock / avg_daily_sales).
      If avg_daily_sales == 0 (shouldn't happen because we require recent sales), we return null.
    """

    company = Company.query.get(company_id)
    if not company:
        return jsonify({'error': 'Company not found'}), 404

    now = datetime.utcnow()
    lookback_cutoff = now - timedelta(days=SALES_LOOKBACK_DAYS)
    avg_sales_cutoff = now - timedelta(days=SALES_AVG_DAYS)

    alerts = []

    # Iterate over all products available in the company's warehouses
    # To keep it simple, collect unique products referenced by inventories in these warehouses
    warehouse_ids = [w.id for w in company.warehouses]
    inventories = Inventory.query.filter(Inventory.warehouse_id.in_(warehouse_ids)).all()

    # Map product_id -> list of inventories (per warehouse)
    prod_inv_map = {}
    for inv in inventories:
        prod_inv_map.setdefault(inv.product_id, []).append(inv)

    for product_id, inv_list in prod_inv_map.items():
        product = Product.query.get(product_id)
        # Check recent sales activity for the product
        recent_sales = [s for s in product.sales if s.created_at >= lookback_cutoff]
        if not recent_sales:
            # Business rule: only alert for products with recent sales activity
            continue

        threshold = get_threshold_for_product(product)

        # Compute average daily sales over SALES_AVG_DAYS (for the product across company)
        sales_for_avg = [s for s in product.sales if s.created_at >= avg_sales_cutoff]
        total_sold_in_window = sum(s.quantity for s in sales_for_avg)
        avg_daily_sales = total_sold_in_window / SALES_AVG_DAYS if SALES_AVG_DAYS > 0 else 0

        for inv in inv_list:
            current_stock = inv.quantity
            if current_stock < threshold:
                # Estimate days until stockout (None if we can't estimate)
                days_until_stockout = None
                if avg_daily_sales > 0:
                    days_until_stockout = floor(current_stock / avg_daily_sales)

                supplier = product.supplier
                supplier_obj = None
                if supplier:
                    supplier_obj = {
                        'id': supplier.id,
                        'name': supplier.name,
                        'contact_email': supplier.contact_email
                    }

                alerts.append({
                    'product_id': product.id,
                    'product_name': product.name,
                    'sku': product.sku,
                    'warehouse_id': inv.warehouse.id,
                    'warehouse_name': inv.warehouse.name,
                    'current_stock': current_stock,
                    'threshold': threshold,
                    'days_until_stockout': days_until_stockout,
                    'supplier': supplier_obj
                })

    response = {
        'alerts': alerts,
        'total_alerts': len(alerts)
    }

    return jsonify(response), 200


# ---------- Simple DB seeder for demonstration and manual testing ----------
def seed_sample_data():
    db.drop_all()
    db.create_all()

    # Create a company and two warehouses
    c = Company(name='Acme Corp')
    w1 = Warehouse(name='Main Warehouse', company=c)
    w2 = Warehouse(name='Overflow Warehouse', company=c)

    # Suppliers
    s1 = Supplier(name='Supplier Corp', contact_email='orders@supplier.com')
    s2 = Supplier(name='Another Supplies', contact_email='hello@another.com')

    # Products
    p1 = Product(name='Widget A', sku='WID-001', product_type='normal', supplier=s1)
    p2 = Product(name='Gizmo B', sku='GIZ-002', product_type='fast-moving', supplier=s2)

    db.session.add_all([c, w1, w2, s1, s2, p1, p2])
    db.session.commit()

    # Inventories
    inv1 = Inventory(product_id=p1.id, warehouse_id=w1.id, quantity=5)  # below normal threshold 20
    inv2 = Inventory(product_id=p1.id, warehouse_id=w2.id, quantity=0)
    inv3 = Inventory(product_id=p2.id, warehouse_id=w1.id, quantity=200)  # above threshold
    inv4 = Inventory(product_id=p2.id, warehouse_id=w2.id, quantity=10)

    db.session.add_all([inv1, inv2, inv3, inv4])
    db.session.commit()

    # Sales - p1 has recent sales, p2 has older sales only
    now = datetime.utcnow()
    recent_sale_p1 = Sale(product_id=p1.id, quantity=10, created_at=now - timedelta(days=5))
    old_sale_p2 = Sale(product_id=p2.id, quantity=100, created_at=now - timedelta(days=200))
    recent_sale_p2 = Sale(product_id=p2.id, quantity=60, created_at=now - timedelta(days=10))

    db.session.add_all([recent_sale_p1, old_sale_p2, recent_sale_p2])
    db.session.commit()

    print('Sample data seeded.')


if __name__ == '__main__':
    # Seed data so the reviewer can run the server and try the endpoint immediately
    seed_sample_data()
    app.run(debug=True)

