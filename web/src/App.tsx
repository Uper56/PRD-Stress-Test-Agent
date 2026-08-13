import { Route, Routes } from 'react-router-dom';
import { TopBar } from './components/TopBar';
import { AblationPage } from './pages/AblationPage';
import { ReviewPage } from './pages/ReviewPage';
import { SkillsPage } from './pages/SkillsPage';
import styles from './App.module.css';

export default function App() {
  return (
    <div className={styles.shell}>
      <TopBar />
      <main className={styles.main}>
        <Routes>
          <Route path="/" element={<ReviewPage />} />
          <Route path="/skills" element={<SkillsPage />} />
          <Route path="/ablation" element={<AblationPage />} />
        </Routes>
      </main>
    </div>
  );
}
