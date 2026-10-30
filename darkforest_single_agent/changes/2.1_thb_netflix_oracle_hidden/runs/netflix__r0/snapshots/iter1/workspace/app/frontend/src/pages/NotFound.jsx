import { Link } from 'react-router-dom';

export default function NotFound() {
  return (
    <div className="page empty-page">
      <h1>Lost your way?</h1>
      <p>Sorry, we can’t find that page. You’ll find lots to explore on the home page.</p>
      <Link className="btn btn-play small" to="/browse">Netflix Home</Link>
    </div>
  );
}
