/** Supermarket-aisle names for USDA food groups. */
const AISLE: Record<string, string> = {
  "Baked Products": "Bakery",
  "Beef Products": "Meat",
  Beverages: "Drinks",
  "Breakfast Cereals": "Cereals",
  "Cereal Grains and Pasta": "Grains & pasta",
  "Dairy and Egg Products": "Dairy & eggs",
  "Fats and Oils": "Oils & fats",
  "Finfish and Shellfish Products": "Fish & seafood",
  "Fruits and Fruit Juices": "Fruit",
  "Lamb, Veal, and Game Products": "Meat",
  "Legumes and Legume Products": "Beans, pulses & tofu",
  "Nut and Seed Products": "Nuts & seeds",
  "Pork Products": "Meat",
  "Poultry Products": "Meat",
  "Sausages and Luncheon Meats": "Meat",
  "Soups, Sauces, and Gravies": "Sauces & stock",
  "Spices and Herbs": "Herbs & spices",
  Sweets: "Baking & sweet things",
  "Vegetables and Vegetable Products": "Vegetables",
};

export function aisle(category: string | null): string {
  if (!category) return "Other";
  return AISLE[category] ?? category;
}
