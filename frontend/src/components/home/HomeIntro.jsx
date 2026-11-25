import { useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import eagleImage from './eagle.png';
import eagleImage2 from './eagle2.png';
import eagleImage3 from './eagle3.png';
import './HomeIntro.css';

const imageSequence = [eagleImage, eagleImage2, eagleImage3, eagleImage2, eagleImage];
const imageChangeDuration = 200;

export function HomeIntro({ onEnter }) {
  const [imageIndex, setImageIndex] = useState(0);
  const [isBlurred, setIsBlurred] = useState(false);
  const [showButton, setShowButton] = useState(false);

  useEffect(() => {
    const imageTimers = imageSequence.map((_, index) =>
      setTimeout(() => setImageIndex(index), index * imageChangeDuration),
    );
    const blurTimer = setTimeout(() => setIsBlurred(true), 1000);
    const contentTimer = setTimeout(() => setShowButton(true), 2000);

    return () => {
      imageTimers.forEach(clearTimeout);
      clearTimeout(blurTimer);
      clearTimeout(contentTimer);
    };
  }, []);

  return (
    <div className="home-intro">
      <motion.img
        src={imageSequence[imageIndex]}
        alt="Águila"
        className="home-intro-eagle"
        animate={{
          filter: isBlurred ? 'blur(12px)' : 'blur(0px)',
        }}
        transition={{
          duration: 1,
          ease: 'easeOut',
        }}
      />

      <AnimatePresence>
        {showButton && (
          <motion.div
            className="home-intro-content"
            initial={{ opacity: 0, y: 24 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.8, ease: 'easeOut' }}
          >
            <h1>GondHawk</h1>
            <motion.button
              type="button"
              className="home-intro-start"
              onClick={onEnter}
              initial={{ opacity: 0, scale: 0.5 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={{ duration: 0.8, delay: 0.15, ease: 'easeOut' }}
            >
              Comenzar →
            </motion.button>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
